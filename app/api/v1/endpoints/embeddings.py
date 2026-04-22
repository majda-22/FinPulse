from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.score import _get_company_or_404
from app.api.v1.schemas import EmbeddingRow
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.session import get_db_dependency

router = APIRouter()
EMBEDDING_SCALAR_FIELDS = (
    "embeddings.text",
    "embeddings.embedding",
    "filings.filed_at",
)


@router.get(
    "/{ticker}/latest_get_{field_name}",
    status_code=status.HTTP_200_OK,
)
def get_latest_embedding_scalar_alias(
    ticker: str,
    field_name: str,
    form_type: str | None = Query(default=None),
    section: str | None = Query(default=None),
    chunk_idx: int | None = Query(default=None, ge=0),
    include_vector: bool = Query(default=True),
    db: Session = Depends(get_db_dependency),
) -> Any:
    return _extract_latest_embedding_scalar(
        db,
        ticker=ticker,
        field_name=field_name,
        form_type=form_type,
        section=section,
        chunk_idx=chunk_idx,
        include_vector=include_vector,
    )


@router.get(
    "/{ticker}/latest/value/{field_name}",
    status_code=status.HTTP_200_OK,
)
def get_latest_embedding_scalar(
    ticker: str,
    field_name: str,
    form_type: str | None = Query(default=None),
    section: str | None = Query(default=None),
    chunk_idx: int | None = Query(default=None, ge=0),
    include_vector: bool = Query(default=True),
    db: Session = Depends(get_db_dependency),
) -> Any:
    return _extract_latest_embedding_scalar(
        db,
        ticker=ticker,
        field_name=field_name,
        form_type=form_type,
        section=section,
        chunk_idx=chunk_idx,
        include_vector=include_vector,
    )


@router.get(
    "/{ticker}/latest",
    response_model=list[EmbeddingRow],
    status_code=status.HTTP_200_OK,
)
def get_latest_embeddings(
    ticker: str,
    form_type: str | None = Query(default=None),
    section: str | None = Query(default=None),
    include_vector: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
) -> list[EmbeddingRow]:
    company = _get_company_or_404(db, ticker)
    rows = _load_latest_embedding_rows(
        db,
        company_id=company.id,
        form_type=form_type,
        section=section,
        include_vector=include_vector,
        limit=limit,
    )
    return rows


@router.get(
    "/{ticker}",
    response_model=list[EmbeddingRow],
    status_code=status.HTTP_200_OK,
)
def get_embeddings(
    ticker: str,
    filing_id: int | None = Query(default=None),
    form_type: str | None = Query(default=None),
    section: str | None = Query(default=None),
    include_vector: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
) -> list[EmbeddingRow]:
    company = _get_company_or_404(db, ticker)

    rows = db.execute(
        _base_embedding_query(
            company_id=company.id,
            filing_id=filing_id,
            form_type=form_type,
            section=section,
        )
        .order_by(Filing.filed_at.desc(), Embedding.chunk_idx.asc(), Embedding.id.asc())
        .limit(limit)
    ).all()

    return [
        _build_embedding_row(embedding, filing, filing_section, include_vector=include_vector)
        for embedding, filing, filing_section in rows
    ]


def _extract_latest_embedding_scalar(
    db: Session,
    *,
    ticker: str,
    field_name: str,
    form_type: str | None,
    section: str | None,
    chunk_idx: int | None,
    include_vector: bool,
) -> Any:
    company = _get_company_or_404(db, ticker)
    rows = _load_latest_embedding_rows(
        db,
        company_id=company.id,
        form_type=form_type,
        section=section,
        chunk_idx=chunk_idx,
        include_vector=include_vector,
        limit=1,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No embedding rows matched the requested filters for the latest filing.",
        )

    row = rows[0]
    resolvers = {
        "embeddings.text": lambda: row.text,
        "embeddings.embedding": lambda: row.embedding,
        "filings.filed_at": lambda: row.filed_at,
    }
    resolver = resolvers.get(field_name)
    if resolver is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": f"Unsupported embedding scalar field {field_name!r}",
                "supported_fields": list(EMBEDDING_SCALAR_FIELDS),
            },
        )
    return resolver()


def _load_latest_embedding_rows(
    db: Session,
    *,
    company_id: int,
    form_type: str | None,
    section: str | None,
    include_vector: bool,
    limit: int,
    chunk_idx: int | None = None,
) -> list[EmbeddingRow]:
    latest_filing_id = db.scalar(
        _base_embedding_query(company_id=company_id, form_type=form_type)
        .with_only_columns(Filing.id)
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )

    if latest_filing_id is None:
        return []

    query = _base_embedding_query(
        company_id=company_id,
        filing_id=latest_filing_id,
        form_type=form_type,
        section=section,
    )
    if chunk_idx is not None:
        query = query.where(Embedding.chunk_idx == chunk_idx)

    rows = db.execute(
        query.order_by(Embedding.chunk_idx.asc(), Embedding.id.asc()).limit(limit)
    ).all()

    return [
        _build_embedding_row(embedding, filing, filing_section, include_vector=include_vector)
        for embedding, filing, filing_section in rows
    ]


def _base_embedding_query(
    *,
    company_id: int,
    filing_id: int | None = None,
    form_type: str | None = None,
    section: str | None = None,
):
    query = (
        select(Embedding, Filing, FilingSection)
        .join(Filing, Filing.id == Embedding.filing_id)
        .join(FilingSection, FilingSection.id == Embedding.filing_section_id)
        .where(Embedding.company_id == company_id)
    )

    if filing_id is not None:
        query = query.where(Embedding.filing_id == filing_id)
    if form_type:
        query = query.where(Filing.form_type == form_type.upper())
    if section:
        query = query.where(FilingSection.section == section)

    return query


def _build_embedding_row(
    embedding: Embedding,
    filing: Filing,
    filing_section: FilingSection,
    *,
    include_vector: bool,
) -> EmbeddingRow:
    return EmbeddingRow(
        id=embedding.id,
        filing_id=embedding.filing_id,
        filing_section_id=embedding.filing_section_id,
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        filed_at=filing.filed_at,
        section=filing_section.section,
        chunk_idx=embedding.chunk_idx,
        text=embedding.text,
        embedding=_serialize_embedding(embedding.embedding, include_vector=include_vector),
        provider=embedding.provider,
        embedding_model=embedding.embedding_model,
        reconstruction_error=_safe_float(embedding.reconstruction_error),
        anomaly_score=_safe_float(embedding.anomaly_score),
        created_at=embedding.created_at,
    )


def _serialize_embedding(value: Any, *, include_vector: bool) -> list[float] | None:
    if not include_vector or value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    try:
        return [float(item) for item in value]
    except TypeError:
        return None


def _safe_float(value: float | None) -> float | None:
    if value is None:
        return None
    return float(value)
