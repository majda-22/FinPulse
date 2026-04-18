from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.session import get_db
from ingestion.company_repo import log_event
from processing.embeddings import MistralEmbeddingClient
from signals.catalog import get_signal_definition
from signals.common import (
    clip01,
    cosine_distance_01,
    cosine_similarity,
    cosine_similarity_01,
    coverage_ratio,
    days_between,
    mean_or_none,
    tfidf_cosine_similarity,
    weighted_average,
)
from signals.history import ANNUAL_FORMS, QUARTERLY_FORMS
from signals.policies import (
    FORWARD_LOOKING_KEYWORDS,
    OPTIMISTIC_FORWARD_ANCHOR,
    PESSIMISTIC_FORWARD_ANCHOR,
    POSITIVE_OUTLOOK_ANCHOR,
    TEXT_COMPONENT_WEIGHTS,
    TEXT_CONFIDENCE_CHUNK_TARGET,
)
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

TEXT_SIGNAL_MODEL_VERSION = "text_signals_v2"
DRIFT_SIGNAL_NAMES = ("rlds", "mda_drift")


@dataclass(slots=True)
class ComputedTextSignal:
    filing_id: int
    company_id: int
    signal_name: str
    signal_value: float | None
    detail: dict[str, Any]
    model_version: str = TEXT_SIGNAL_MODEL_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_section_drift_signals(
    db: Session,
    *,
    current_filing_id: int,
    model_version: str = TEXT_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, current_filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={current_filing_id} not found in database")

    signals = [
        _build_drift_signal(
            db,
            filing=filing,
            previous_filing=_get_comparison_filing(db, filing=filing, section_name="risk_factors"),
            section_name="risk_factors",
            signal_name="rlds",
            model_version=model_version,
        ),
        _build_drift_signal(
            db,
            filing=filing,
            previous_filing=_get_comparison_filing(db, filing=filing, section_name="mda"),
            section_name="mda",
            signal_name="mda_drift",
            model_version=model_version,
        ),
    ]
    return [signal.to_dict() for signal in signals]


def compute_text_signals(
    db: Session,
    *,
    filing_id: int,
    model_version: str = TEXT_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = [
        _build_drift_signal(
            db,
            filing=filing,
            previous_filing=_get_comparison_filing(db, filing=filing, section_name="risk_factors"),
            section_name="risk_factors",
            signal_name="rlds",
            model_version=model_version,
        ),
        _build_drift_signal(
            db,
            filing=filing,
            previous_filing=_get_comparison_filing(db, filing=filing, section_name="mda"),
            section_name="mda",
            signal_name="mda_drift",
            model_version=model_version,
        ),
        _build_text_sentiment_signal(
            db,
            filing=filing,
            model_version=model_version,
        ),
        _build_forward_pessimism_signal(
            db,
            filing=filing,
            model_version=model_version,
        ),
    ]

    return [signal.to_dict() for signal in signals]


def compute_and_store_text_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    model_version: str = TEXT_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    if db is None:
        with get_db() as session:
            return compute_and_store_text_signals(
                filing_id,
                db=session,
                model_version=model_version,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = compute_text_signals(db, filing_id=filing_id, model_version=model_version)
    upsert_signal_scores(db, signals)

    mark_signal_stage(filing, text_scored=True, processing_status="text_signal_scored")
    filing.last_error_message = None

    log_event(
        db,
        event_type="signal_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "text_signals",
            "model_version": model_version,
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"]
                for signal in signals
                if signal["signal_value"] is None
            ],
        },
    )
    return signals


def compute_and_store_section_signals(
    current_filing_id: int,
    *,
    db: Session | None = None,
    model_version: str = TEXT_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    return compute_and_store_text_signals(
        current_filing_id,
        db=db,
        model_version=model_version,
    )


def _build_drift_signal(
    db: Session,
    *,
    filing: Filing,
    previous_filing: Filing | None,
    section_name: str,
    signal_name: str,
    model_version: str,
) -> ComputedTextSignal:
    definition = get_signal_definition(signal_name)
    if previous_filing is None:
        return _not_available_text_signal(
            filing=filing,
            signal_name=signal_name,
            model_version=model_version,
            availability_reason="no_previous_comparable_filing",
            extra_detail={
                "section": section_name,
                "description": definition.description if definition else "",
            },
        )

    current_text = _load_section_text(db, filing_id=filing.id, section_name=section_name)
    previous_text = _load_section_text(db, filing_id=previous_filing.id, section_name=section_name)
    current_chunks = _load_section_chunks(db, filing_id=filing.id, section_name=section_name)
    previous_chunks = _load_section_chunks(db, filing_id=previous_filing.id, section_name=section_name)

    tfidf_drift = None
    if current_text and previous_text:
        tfidf_similarity = tfidf_cosine_similarity(current_text, previous_text)
        tfidf_drift = clip01(1.0 - tfidf_similarity)

    semantic_novelty = None
    top_novel_paragraphs: list[dict[str, Any]] = []
    if current_chunks and previous_chunks:
        semantic_novelty, top_novel_paragraphs = _semantic_novelty(current_chunks, previous_chunks)

    raw_score, defined_components = weighted_average(
        {
            "tfidf_drift": tfidf_drift,
            "semantic_novelty": semantic_novelty,
        },
        TEXT_COMPONENT_WEIGHTS,
    )

    normalized_score = None
    gap_days = days_between(filing.filed_at, previous_filing.filed_at)
    if raw_score is not None:
        normalized_score = clip01(raw_score / (gap_days / 365.0))

    coverage = coverage_ratio(
        {
            "tfidf_drift": tfidf_drift,
            "semantic_novelty": semantic_novelty,
        },
        expected_count=2,
    )
    confidence = clip01(
        (0.7 * clip01(min(len(current_chunks), len(previous_chunks)) / TEXT_CONFIDENCE_CHUNK_TARGET))
        + (0.3 * coverage)
    )

    return ComputedTextSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=signal_name,
        signal_value=normalized_score,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "section": section_name,
            "tfidf_drift": tfidf_drift,
            "semantic_novelty": semantic_novelty,
            "raw_score": raw_score,
            "normalized_score": normalized_score,
            "coverage_ratio": coverage,
            "confidence": confidence,
            "history_depth": 1,
            "days_between_filings": gap_days,
            "component_weights": dict(TEXT_COMPONENT_WEIGHTS),
            "component_scores": defined_components,
            "current_chunk_count": len(current_chunks),
            "previous_chunk_count": len(previous_chunks),
            "comparison_filing_id": previous_filing.id,
            "comparison_accession_number": previous_filing.accession_number,
            "comparison_filed_at": previous_filing.filed_at.isoformat(),
            "current_accession_number": filing.accession_number,
            "current_filed_at": filing.filed_at.isoformat(),
            "comparison_basis": _comparison_basis(filing=filing, section_name=section_name),
            "signal_category": "text",
            "signal_role": "base",
            "top_novel_paragraphs": top_novel_paragraphs,
            "model_version": model_version,
        },
    )


def _build_text_sentiment_signal(
    db: Session,
    *,
    filing: Filing,
    model_version: str,
) -> ComputedTextSignal:
    definition = get_signal_definition("text_sentiment")
    current_chunks = _load_section_chunks(db, filing_id=filing.id, section_name="mda")
    if not current_chunks:
        return _not_available_text_signal(
            filing=filing,
            signal_name="text_sentiment",
            model_version=model_version,
            availability_reason="missing_mda_embeddings",
            extra_detail={
                "description": definition.description if definition else "",
                "section": "mda",
            },
        )

    method = "embedding"
    paragraph_scores: list[float] = []
    try:
        anchor_vector = _anchor_embedding()
        for chunk in current_chunks:
            paragraph_scores.append(cosine_similarity_01(anchor_vector, chunk["embedding"]))
    except Exception:
        method = "lexical_fallback"
        paragraph_scores = [
            tfidf_cosine_similarity(chunk["text"], POSITIVE_OUTLOOK_ANCHOR)
            for chunk in current_chunks
            if chunk["text"]
        ]

    signal_value = mean_or_none(paragraph_scores)
    confidence = clip01(
        (0.7 * clip01(len(current_chunks) / TEXT_CONFIDENCE_CHUNK_TARGET))
        + (0.3 * (1.0 if method == "embedding" else 0.75))
    )

    return ComputedTextSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="text_sentiment",
        signal_value=signal_value,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "section": "mda",
            "anchor_text": POSITIVE_OUTLOOK_ANCHOR,
            "method": method,
            "paragraph_count": len(current_chunks),
            "coverage_ratio": 1.0 if signal_value is not None else 0.0,
            "confidence": confidence,
            "history_depth": 0,
            "signal_category": "text",
            "signal_role": "auxiliary",
            "paragraph_scores": paragraph_scores,
            "model_version": model_version,
        },
    )


def _build_forward_pessimism_signal(
    db: Session,
    *,
    filing: Filing,
    model_version: str,
) -> ComputedTextSignal:
    definition = get_signal_definition("forward_pessimism")
    current_chunks = _load_section_chunks(db, filing_id=filing.id, section_name="mda")
    if not current_chunks:
        return _not_available_text_signal(
            filing=filing,
            signal_name="forward_pessimism",
            model_version=model_version,
            availability_reason="missing_mda_embeddings",
            extra_detail={
                "description": definition.description if definition else "",
                "section": "mda",
            },
        )

    forward_chunks = [
        chunk
        for chunk in current_chunks
        if _is_forward_looking_text(chunk["text"])
    ]
    paragraph_basis = "forward_looking_only"
    if not forward_chunks:
        forward_chunks = current_chunks
        paragraph_basis = "all_mda_fallback"

    method = "embedding"
    paragraph_tones: list[float] = []
    try:
        optimistic_anchor = _optimistic_anchor_embedding()
        pessimistic_anchor = _pessimistic_anchor_embedding()
        for chunk in forward_chunks:
            optimistic_similarity = cosine_similarity(optimistic_anchor, chunk["embedding"])
            pessimistic_similarity = cosine_similarity(pessimistic_anchor, chunk["embedding"])
            paragraph_tones.append(pessimistic_similarity - optimistic_similarity)
    except Exception:
        method = "lexical_fallback"
        for chunk in forward_chunks:
            optimistic_similarity = tfidf_cosine_similarity(chunk["text"], OPTIMISTIC_FORWARD_ANCHOR)
            pessimistic_similarity = tfidf_cosine_similarity(chunk["text"], PESSIMISTIC_FORWARD_ANCHOR)
            paragraph_tones.append(pessimistic_similarity - optimistic_similarity)

    forward_pessimism = mean_or_none(paragraph_tones)
    normalized = None if forward_pessimism is None else clip01((forward_pessimism + 1.0) / 2.0)
    confidence = clip01(
        (0.7 * clip01(len(forward_chunks) / TEXT_CONFIDENCE_CHUNK_TARGET))
        + (0.3 * (1.0 if method == "embedding" else 0.75))
    )

    return ComputedTextSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="forward_pessimism",
        signal_value=normalized,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "section": "mda",
            "method": method,
            "paragraph_basis": paragraph_basis,
            "paragraph_count": len(forward_chunks),
            "raw_forward_pessimism": forward_pessimism,
            "coverage_ratio": 1.0 if normalized is not None else 0.0,
            "confidence": confidence,
            "history_depth": 0,
            "signal_category": "text",
            "signal_role": "base",
            "paragraph_tones": paragraph_tones,
            "optimistic_anchor": OPTIMISTIC_FORWARD_ANCHOR,
            "pessimistic_anchor": PESSIMISTIC_FORWARD_ANCHOR,
            "model_version": model_version,
        },
    )


def _not_available_text_signal(
    *,
    filing: Filing,
    signal_name: str,
    model_version: str,
    availability_reason: str,
    extra_detail: dict[str, Any],
) -> ComputedTextSignal:
    return ComputedTextSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=signal_name,
        signal_value=None,
        model_version=model_version,
        detail={
            "availability_reason": availability_reason,
            "coverage_ratio": 0.0,
            "confidence": 0.0,
            "history_depth": 0,
            "signal_category": "text",
            "signal_role": "base" if signal_name != "text_sentiment" else "auxiliary",
            "model_version": model_version,
            **extra_detail,
        },
    )


def _comparison_basis(*, filing: Filing, section_name: str) -> str:
    if filing.form_type in QUARTERLY_FORMS and section_name == "risk_factors":
        return "most_recent_annual_risk_baseline"
    if filing.form_type in QUARTERLY_FORMS and section_name == "mda":
        return "prior_quarter_mda"
    return "prior_annual_same_section"


def _get_comparison_filing(
    db: Session,
    *,
    filing: Filing,
    section_name: str,
) -> Filing | None:
    if filing.form_type in QUARTERLY_FORMS:
        if section_name == "risk_factors":
            return _get_latest_annual_baseline(db, filing=filing)
        return _get_previous_quarterly_filing(db, filing=filing)
    return _get_previous_annual_filing(db, filing=filing)


def _get_previous_annual_filing(db: Session, *, filing: Filing) -> Filing | None:
    return db.scalar(
        select(Filing)
        .where(
            Filing.company_id == filing.company_id,
            Filing.form_type.in_(tuple(ANNUAL_FORMS)),
            Filing.filed_at < filing.filed_at,
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )


def _get_previous_quarterly_filing(db: Session, *, filing: Filing) -> Filing | None:
    return db.scalar(
        select(Filing)
        .where(
            Filing.company_id == filing.company_id,
            Filing.form_type.in_(tuple(QUARTERLY_FORMS)),
            Filing.filed_at < filing.filed_at,
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )


def _get_latest_annual_baseline(db: Session, *, filing: Filing) -> Filing | None:
    return _get_previous_annual_filing(db, filing=filing)


def _load_section_text(db: Session, *, filing_id: int, section_name: str) -> str | None:
    rows = db.scalars(
        select(FilingSection.text)
        .where(
            FilingSection.filing_id == filing_id,
            FilingSection.section == section_name,
        )
        .order_by(FilingSection.sequence_idx.asc())
    ).all()
    if not rows:
        return None
    text = "\n".join(row.strip() for row in rows if row and row.strip())
    return text or None


def _load_section_chunks(
    db: Session,
    *,
    filing_id: int,
    section_name: str,
) -> list[dict[str, Any]]:
    settings = get_settings()
    rows = db.execute(
        select(Embedding.text, Embedding.embedding)
        .join(FilingSection, FilingSection.id == Embedding.filing_section_id)
        .where(
            Embedding.filing_id == filing_id,
            FilingSection.section == section_name,
            Embedding.provider == settings.embedding_provider,
            Embedding.embedding_model == settings.mistral_embedding_model,
        )
        .order_by(FilingSection.sequence_idx.asc(), Embedding.chunk_idx.asc())
    ).all()

    return [
        {"text": text, "embedding": list(embedding)}
        for text, embedding in rows
    ]


def _semantic_novelty(
    current_chunks: Sequence[dict[str, Any]],
    previous_chunks: Sequence[dict[str, Any]],
) -> tuple[float | None, list[dict[str, Any]]]:
    if not current_chunks or not previous_chunks:
        return None, []

    previous_vectors = np.asarray([chunk["embedding"] for chunk in previous_chunks], dtype=float)
    previous_norms = np.linalg.norm(previous_vectors, axis=1, keepdims=True)
    previous_norms[previous_norms == 0.0] = 1.0
    previous_unit = previous_vectors / previous_norms

    novelty_rows: list[dict[str, Any]] = []
    novelty_values: list[float] = []

    for chunk in current_chunks:
        current_vector = np.asarray(chunk["embedding"], dtype=float)
        current_norm = float(np.linalg.norm(current_vector))
        if current_norm == 0.0:
            best_similarity = 0.0
        else:
            similarities = previous_unit @ (current_vector / current_norm)
            best_similarity = float(np.max(similarities))
        novelty_distance = clip01((1.0 - best_similarity) / 2.0)
        novelty_values.append(novelty_distance)
        novelty_rows.append(
            {
                "text": chunk["text"],
                "best_match_similarity": max(-1.0, min(1.0, best_similarity)),
                "novelty_distance": novelty_distance,
            }
        )

    novelty_rows.sort(key=lambda row: row["novelty_distance"], reverse=True)
    return mean_or_none(novelty_values), novelty_rows[:5]


@lru_cache(maxsize=4)
def _anchor_embedding() -> tuple[float, ...]:
    settings = get_settings()
    with MistralEmbeddingClient(
        api_key=settings.mistral_api_key,
        model=settings.mistral_embedding_model,
        base_url=settings.mistral_api_base,
    ) as client:
        batch = client.embed_texts([POSITIVE_OUTLOOK_ANCHOR])
    return tuple(float(value) for value in batch.vectors[0])


@lru_cache(maxsize=4)
def _optimistic_anchor_embedding() -> tuple[float, ...]:
    settings = get_settings()
    with MistralEmbeddingClient(
        api_key=settings.mistral_api_key,
        model=settings.mistral_embedding_model,
        base_url=settings.mistral_api_base,
    ) as client:
        batch = client.embed_texts([OPTIMISTIC_FORWARD_ANCHOR])
    return tuple(float(value) for value in batch.vectors[0])


@lru_cache(maxsize=4)
def _pessimistic_anchor_embedding() -> tuple[float, ...]:
    settings = get_settings()
    with MistralEmbeddingClient(
        api_key=settings.mistral_api_key,
        model=settings.mistral_embedding_model,
        base_url=settings.mistral_api_base,
    ) as client:
        batch = client.embed_texts([PESSIMISTIC_FORWARD_ANCHOR])
    return tuple(float(value) for value in batch.vectors[0])


def _is_forward_looking_text(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in FORWARD_LOOKING_KEYWORDS)
