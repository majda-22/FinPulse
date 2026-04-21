from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.score import _get_company_or_404
from app.api.v1.schemas import EmbeddingRow
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.session import get_db_dependency

router = APIRouter()


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

    latest_filing_id = db.scalar(
        _base_embedding_query(company_id=company.id, form_type=form_type)
        .with_only_columns(Filing.id)
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )

    if latest_filing_id is None:
        return []

    rows = db.execute(
        _base_embedding_query(
            company_id=company.id,
            filing_id=latest_filing_id,
            form_type=form_type,
            section=section,
        )
        .order_by(Embedding.chunk_idx.asc(), Embedding.id.asc())
        .limit(limit)
    ).all()

    return [_build_embedding_row(embedding, filing, filing_section, include_vector=include_vector) for embedding, filing, filing_section in rows]


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
