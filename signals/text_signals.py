from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import ceil
import re
from typing import Any, Sequence

import numpy as np
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.models.signal_score import SignalScore
from app.db.session import get_db
from ingestion.company_repo import log_event
from processing.finbert import (
    FINBERT_MODEL_NAME,
    get_finbert_pipeline,
    normalize_finbert_batch_results,
)
from signals.catalog import get_signal_definition
from signals.common import (
    clip01,
    coverage_ratio,
    days_between,
    mean_or_none,
    tfidf_cosine_similarity,
    weighted_average,
)
from signals.history import ANNUAL_FORMS, QUARTERLY_FORMS
from signals.policies import (
    FORWARD_LOOKING_KEYWORDS,
    TEXT_COMPONENT_WEIGHTS,
    TEXT_CONFIDENCE_CHUNK_TARGET,
)
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

TEXT_SIGNAL_MODEL_VERSION = "text_signals_v4"
DRIFT_SIGNAL_NAMES = ("rlds", "mda_drift")
TEXT_SENTIMENT_SECTIONS = ("mda", "forward_looking")
DRIFT_RESCALING_FLOOR = 0.02
DRIFT_RESCALING_CAP = 0.25
DRIFT_TOPK_RATIO = 0.25
DRIFT_TOPK_MIN_COUNT = 3
DRIFT_SENTENCE_MIN_CHARS = 40
DRIFT_HISTORY_MIN_COUNT = 3
DRIFT_HISTORY_MIN_STD = 0.005
DRIFT_ZSCORE_CAP = 2.0


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

    finbert_analysis = _analyze_finbert_text_signals(db, filing_id=filing.id)

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
            filing=filing,
            model_version=model_version,
            analysis=finbert_analysis,
        ),
        _build_forward_pessimism_signal(
            filing=filing,
            model_version=model_version,
            analysis=finbert_analysis,
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
    tfidf_summary: dict[str, Any] | None = None
    if current_text and previous_text:
        tfidf_summary = _local_tfidf_drift_summary(current_text, previous_text)
        tfidf_drift = tfidf_summary["top_k_drift"]

    semantic_novelty = None
    top_novel_paragraphs: list[dict[str, Any]] = []
    semantic_summary: dict[str, Any] | None = None
    if current_chunks and previous_chunks:
        semantic_summary = _semantic_novelty_summary(current_chunks, previous_chunks)
        semantic_novelty = semantic_summary["top_k_mean"]
        top_novel_paragraphs = semantic_summary["top_rows"]

    raw_score, defined_components = weighted_average(
        {
            "tfidf_drift": tfidf_drift,
            "semantic_novelty": semantic_novelty,
        },
        TEXT_COMPONENT_WEIGHTS,
    )

    raw_rescaled_score = None
    history_relative_score = None
    history_zscore = None
    history_mean = None
    history_std = None
    historical_raw_scores: list[float] = []
    scoring_mode = "not_available"
    gap_days = days_between(filing.filed_at, previous_filing.filed_at)
    if raw_score is not None:
        raw_rescaled_score = _rescale_drift_score(raw_score)
        historical_raw_scores = _load_historical_drift_raw_scores(
            db,
            filing=filing,
            signal_name=signal_name,
            model_version=model_version,
        )
        history_relative_score, history_zscore, history_mean, history_std = _history_relative_drift_score(
            raw_score=raw_score,
            historical_raw_scores=historical_raw_scores,
        )
        normalized_score = history_relative_score if history_relative_score is not None else raw_rescaled_score
        scoring_mode = "history_relative" if history_relative_score is not None else "bounded_raw_rescale"
    else:
        normalized_score = None

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
            "tfidf_summary": tfidf_summary,
            "semantic_novelty": semantic_novelty,
            "semantic_summary": semantic_summary,
            "raw_score": raw_score,
            "raw_rescaled_score": raw_rescaled_score,
            "history_relative_score": history_relative_score,
            "history_zscore": history_zscore,
            "historical_raw_mean": history_mean,
            "historical_raw_std": history_std,
            "historical_raw_count": len(historical_raw_scores),
            "normalized_score": normalized_score,
            "scoring_mode": scoring_mode,
            "rescaling_floor": DRIFT_RESCALING_FLOOR,
            "rescaling_cap": DRIFT_RESCALING_CAP,
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


def _rescale_drift_score(raw_score: float) -> float:
    if raw_score <= DRIFT_RESCALING_FLOOR:
        return 0.0
    if raw_score >= DRIFT_RESCALING_CAP:
        return 1.0
    return clip01(
        (raw_score - DRIFT_RESCALING_FLOOR)
        / (DRIFT_RESCALING_CAP - DRIFT_RESCALING_FLOOR)
    )


def _history_relative_drift_score(
    *,
    raw_score: float,
    historical_raw_scores: Sequence[float],
) -> tuple[float | None, float | None, float | None, float | None]:
    if len(historical_raw_scores) < DRIFT_HISTORY_MIN_COUNT:
        return None, None, None, None

    history_mean = float(np.mean(historical_raw_scores))
    history_std = float(np.std(historical_raw_scores))
    if history_std < DRIFT_HISTORY_MIN_STD:
        return None, None, history_mean, history_std

    zscore = float((raw_score - history_mean) / history_std)
    score = clip01(max(0.0, zscore) / DRIFT_ZSCORE_CAP)
    return score, zscore, history_mean, history_std


def _load_historical_drift_raw_scores(
    db: Session,
    *,
    filing: Filing,
    signal_name: str,
    model_version: str,
) -> list[float]:
    rows = db.scalars(
        select(SignalScore)
        .join(Filing, Filing.id == SignalScore.filing_id)
        .where(
            SignalScore.company_id == filing.company_id,
            SignalScore.signal_name == signal_name,
            SignalScore.model_version == model_version,
            or_(
                Filing.filed_at < filing.filed_at,
                and_(Filing.filed_at == filing.filed_at, Filing.id < filing.id),
            ),
        )
        .order_by(Filing.filed_at.asc(), Filing.id.asc())
    ).all()

    raw_scores: list[float] = []
    for row in rows:
        if not isinstance(row.detail, dict):
            continue
        raw_score = row.detail.get("raw_score")
        if isinstance(raw_score, (int, float)):
            raw_scores.append(float(raw_score))
    return raw_scores


def _build_text_sentiment_signal(
    *,
    filing: Filing,
    model_version: str,
    analysis: dict[str, Any],
) -> ComputedTextSignal:
    definition = get_signal_definition("text_sentiment")
    if analysis["status"] != "ok" or analysis.get("text_sentiment") is None:
        return _not_available_text_signal(
            filing=filing,
            signal_name="text_sentiment",
            model_version=model_version,
            availability_reason=str(analysis.get("reason") or "missing_finbert_inputs"),
            extra_detail={
                "description": definition.description if definition else "",
                "section": "+".join(TEXT_SENTIMENT_SECTIONS),
            },
        )

    signal_value = float(analysis["text_sentiment"])
    confidence = float(analysis["confidence"])

    return ComputedTextSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="text_sentiment",
        signal_value=signal_value,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "section": "+".join(TEXT_SENTIMENT_SECTIONS),
            "method": "finbert",
            "model": FINBERT_MODEL_NAME,
            "paragraph_basis": str(analysis["paragraph_basis"]),
            "paragraph_count": int(analysis["paragraph_count"]),
            "paragraphs_scored": int(analysis["paragraphs_scored_all"]),
            "paragraphs_failed": int(analysis["paragraphs_failed"]),
            "avg_positive": float(analysis["avg_positive_all"]),
            "avg_negative": float(analysis["avg_negative_all"]),
            "avg_neutral": float(analysis["avg_neutral_all"]),
            "coverage_ratio": float(analysis["coverage_ratio_all"]),
            "confidence": confidence,
            "history_depth": 0,
            "signal_category": "text",
            "signal_role": "auxiliary",
            "sample_scores": analysis["sample_scores_all"],
            "model_version": model_version,
        },
    )


def _build_forward_pessimism_signal(
    *,
    filing: Filing,
    model_version: str,
    analysis: dict[str, Any],
) -> ComputedTextSignal:
    definition = get_signal_definition("forward_pessimism")
    if analysis["status"] != "ok" or analysis.get("forward_pessimism") is None:
        return _not_available_text_signal(
            filing=filing,
            signal_name="forward_pessimism",
            model_version=model_version,
            availability_reason=str(analysis.get("reason") or "missing_finbert_inputs"),
            extra_detail={
                "description": definition.description if definition else "",
                "section": "+".join(TEXT_SENTIMENT_SECTIONS),
            },
        )

    normalized = float(analysis["forward_pessimism"])
    confidence = float(analysis["confidence"])

    return ComputedTextSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="forward_pessimism",
        signal_value=normalized,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "section": "+".join(TEXT_SENTIMENT_SECTIONS),
            "method": "finbert",
            "model": FINBERT_MODEL_NAME,
            "paragraph_basis": str(analysis["forward_paragraph_basis"]),
            "paragraph_count": int(analysis["forward_paragraph_count"]),
            "paragraphs_scored": int(analysis["paragraphs_scored_forward"]),
            "paragraphs_failed": int(analysis["paragraphs_failed"]),
            "raw_forward_pessimism": float(analysis["raw_pessimism_forward"]),
            "avg_positive": float(analysis["avg_positive_forward"]),
            "avg_negative": float(analysis["avg_negative_forward"]),
            "avg_neutral": float(analysis["avg_neutral_forward"]),
            "coverage_ratio": float(analysis["coverage_ratio_forward"]),
            "confidence": confidence,
            "history_depth": 0,
            "signal_category": "text",
            "signal_role": "base",
            "sample_scores": analysis["sample_scores_forward"],
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


def _analyze_finbert_text_signals(
    db: Session,
    *,
    filing_id: int,
) -> dict[str, Any]:
    paragraph_rows = _load_text_analysis_paragraphs(db, filing_id=filing_id)
    if not paragraph_rows:
        return {
            "status": "not_available",
            "reason": "no_paragraphs",
        }

    try:
        scored_rows = _score_paragraphs_with_finbert(paragraph_rows)
    except Exception as exc:
        return {
            "status": "not_available",
            "reason": "finbert_unavailable",
            "error": str(exc),
            "paragraph_basis": "mda_and_forward_looking",
            "paragraph_count": len(paragraph_rows),
            "paragraphs_failed": len(paragraph_rows),
        }

    if not scored_rows:
        return {
            "status": "not_available",
            "reason": "all_paragraphs_failed",
            "paragraph_basis": "mda_and_forward_looking",
            "paragraph_count": len(paragraph_rows),
            "paragraphs_failed": len(paragraph_rows),
        }

    forward_rows = [row for row in scored_rows if row["is_forward_looking"]]
    forward_basis = "forward_looking_subset"
    if not forward_rows:
        forward_rows = scored_rows
        forward_basis = "all_mda_forward_sections_fallback"

    avg_positive_all = mean_or_none([row["positive"] for row in scored_rows])
    avg_negative_all = mean_or_none([row["negative"] for row in scored_rows])
    avg_neutral_all = mean_or_none([row["neutral"] for row in scored_rows])

    avg_positive_forward = mean_or_none([row["positive"] for row in forward_rows])
    avg_negative_forward = mean_or_none([row["negative"] for row in forward_rows])
    avg_neutral_forward = mean_or_none([row["neutral"] for row in forward_rows])

    if (
        avg_positive_all is None
        or avg_negative_all is None
        or avg_positive_forward is None
        or avg_negative_forward is None
    ):
        return {
            "status": "not_available",
            "reason": "all_paragraphs_failed",
            "paragraph_basis": "mda_and_forward_looking",
            "paragraph_count": len(paragraph_rows),
            "paragraphs_failed": len(paragraph_rows),
        }

    raw_pessimism_forward = avg_negative_forward - avg_positive_forward
    forward_pessimism = clip01((raw_pessimism_forward + 1.0) / 2.0)
    text_sentiment = clip01(avg_positive_all)
    coverage_all = clip01(len(scored_rows) / max(len(paragraph_rows), 1))
    coverage_forward = clip01(len(forward_rows) / max(len(paragraph_rows), 1))
    confidence = clip01(
        (0.7 * clip01(len(scored_rows) / TEXT_CONFIDENCE_CHUNK_TARGET))
        + (0.3 * coverage_all)
    )

    return {
        "status": "ok",
        "reason": None,
        "paragraph_basis": "mda_and_forward_looking",
        "paragraph_count": len(paragraph_rows),
        "paragraphs_scored_all": len(scored_rows),
        "paragraphs_failed": len(paragraph_rows) - len(scored_rows),
        "avg_positive_all": avg_positive_all,
        "avg_negative_all": avg_negative_all,
        "avg_neutral_all": avg_neutral_all if avg_neutral_all is not None else 0.0,
        "coverage_ratio_all": coverage_all,
        "text_sentiment": text_sentiment,
        "forward_paragraph_basis": forward_basis,
        "forward_paragraph_count": len(forward_rows),
        "paragraphs_scored_forward": len(forward_rows),
        "avg_positive_forward": avg_positive_forward,
        "avg_negative_forward": avg_negative_forward,
        "avg_neutral_forward": avg_neutral_forward if avg_neutral_forward is not None else 0.0,
        "coverage_ratio_forward": coverage_forward,
        "raw_pessimism_forward": raw_pessimism_forward,
        "forward_pessimism": forward_pessimism,
        "confidence": confidence,
        "sample_scores_all": _sample_score_rows(scored_rows),
        "sample_scores_forward": _sample_score_rows(forward_rows),
    }


def _load_text_analysis_paragraphs(
    db: Session,
    *,
    filing_id: int,
    max_paragraphs: int = 30,
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(FilingSection.section, FilingSection.text)
        .where(
            FilingSection.filing_id == filing_id,
            FilingSection.section.in_(TEXT_SENTIMENT_SECTIONS),
        )
        .order_by(FilingSection.sequence_idx.asc())
    ).all()

    paragraph_rows: list[dict[str, Any]] = []
    for section_name, section_text in rows:
        for paragraph in _split_text_paragraphs(section_text):
            paragraph_rows.append(
                {
                    "section": section_name,
                    "text": paragraph,
                    "is_forward_looking": (
                        section_name == "forward_looking" or _is_forward_looking_text(paragraph)
                    ),
                }
            )
            if len(paragraph_rows) >= max_paragraphs:
                return paragraph_rows

    return paragraph_rows


def _split_text_paragraphs(text: str, *, max_chunk_chars: int = 800) -> list[str]:
    if not text or not text.strip():
        return []

    blocks = [
        _normalize_whitespace(block)
        for block in re.split(r"\n\s*\n+", text)
        if block and block.strip()
    ]
    if not blocks:
        blocks = [_normalize_whitespace(text)]

    paragraphs: list[str] = []
    for block in blocks:
        if len(block) < 50:
            continue
        if len(block) <= max_chunk_chars:
            paragraphs.append(block)
            continue
        paragraphs.extend(_chunk_long_text(block, max_chunk_chars=max_chunk_chars))
    return paragraphs


def _split_text_drift_units(text: str, *, max_chunk_chars: int = 400) -> list[str]:
    if not text or not text.strip():
        return []

    normalized = _normalize_whitespace(text)
    if not normalized:
        return []

    sentence_candidates = [
        _normalize_whitespace(sentence)
        for sentence in re.split(r"(?<=[.!?;:])\s+", normalized)
        if sentence and sentence.strip()
    ]

    units: list[str] = []
    for sentence in sentence_candidates:
        if len(sentence) < DRIFT_SENTENCE_MIN_CHARS:
            continue
        if len(sentence) <= max_chunk_chars:
            units.append(sentence)
            continue
        units.extend(_chunk_long_text(sentence, max_chunk_chars=max_chunk_chars))

    if len(units) >= DRIFT_TOPK_MIN_COUNT:
        return units

    return _split_text_paragraphs(text, max_chunk_chars=max_chunk_chars)


def _chunk_long_text(text: str, *, max_chunk_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", _normalize_whitespace(text))
    if len(sentences) <= 1:
        return [
            text[idx: idx + max_chunk_chars].strip()
            for idx in range(0, len(text), max_chunk_chars)
            if text[idx: idx + max_chunk_chars].strip()
        ]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
        if len(sentence) <= max_chunk_chars:
            current = sentence
            continue
        chunks.extend(
            sentence[idx: idx + max_chunk_chars].strip()
            for idx in range(0, len(sentence), max_chunk_chars)
            if sentence[idx: idx + max_chunk_chars].strip()
        )
        current = ""

    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if len(chunk) >= 50]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _get_finbert():
    return get_finbert_pipeline()


def _score_paragraphs_with_finbert(
    paragraph_rows: Sequence[dict[str, Any]],
    *,
    batch_size: int = 8,
) -> list[dict[str, Any]]:
    finbert = _get_finbert()
    scored_rows: list[dict[str, Any]] = []

    for start in range(0, len(paragraph_rows), batch_size):
        batch_rows = list(paragraph_rows[start:start + batch_size])
        batch_texts = [row["text"][:1500] for row in batch_rows]
        try:
            raw_results = finbert(batch_texts)
        except Exception:
            continue

        normalized_results = _normalize_finbert_batch_results(raw_results, expected_count=len(batch_rows))
        for row, result in zip(batch_rows, normalized_results):
            if result is None:
                continue
            scored_rows.append(
                {
                    **row,
                    "positive": result["positive"],
                    "negative": result["negative"],
                    "neutral": result["neutral"],
                }
            )

    return scored_rows


def _normalize_finbert_batch_results(
    raw_results: Any,
    *,
    expected_count: int,
) -> list[dict[str, float] | None]:
    return normalize_finbert_batch_results(raw_results, expected_count=expected_count)


def _normalize_finbert_result(raw_result: Any) -> dict[str, float] | None:
    if isinstance(raw_result, dict):
        entries = [raw_result]
    elif isinstance(raw_result, list):
        if not raw_result:
            return None
        if isinstance(raw_result[0], dict):
            entries = raw_result
        elif isinstance(raw_result[0], list) and raw_result[0] and isinstance(raw_result[0][0], dict):
            entries = raw_result[0]
        else:
            return None
    else:
        return None

    scores = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    for entry in entries:
        label = str(entry.get("label", "")).lower()
        if label in scores:
            scores[label] = float(entry.get("score", 0.0))
    return scores


def _sample_score_rows(rows: Sequence[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in list(rows)[:limit]:
        samples.append(
            {
                "section": row["section"],
                "is_forward_looking": bool(row["is_forward_looking"]),
                "positive": round(float(row["positive"]), 4),
                "negative": round(float(row["negative"]), 4),
                "neutral": round(float(row["neutral"]), 4),
                "text_preview": str(row["text"])[:160],
            }
        )
    return samples


def _local_tfidf_drift_summary(
    current_text: str,
    previous_text: str,
) -> dict[str, Any]:
    current_units = _split_text_drift_units(current_text)
    previous_units = _split_text_drift_units(previous_text)

    global_similarity = tfidf_cosine_similarity(current_text, previous_text)
    global_drift = clip01(1.0 - global_similarity)

    if not current_units or not previous_units:
        return {
            "global_similarity": global_similarity,
            "global_drift": global_drift,
            "top_k_drift": global_drift,
            "unit_count": 0,
            "comparison_unit_count": 0,
            "top_k_count": 0,
            "top_changes": [],
            "aggregation": "global_fallback",
            "unit_basis": "sentence",
        }

    novelty_rows: list[dict[str, Any]] = []

    for unit in current_units:
        best_similarity = max(
            tfidf_cosine_similarity(unit, comparison_unit)
            for comparison_unit in previous_units
        )
        lexical_drift = clip01(1.0 - best_similarity)
        novelty_rows.append(
            {
                "text": unit,
                "best_match_similarity": best_similarity,
                "drift": lexical_drift,
            }
        )

    novelty_rows.sort(key=lambda row: row["drift"], reverse=True)
    top_k_count = _top_k_count(len(novelty_rows))
    top_rows = novelty_rows[:top_k_count]
    top_k_drift = mean_or_none(row["drift"] for row in top_rows)

    return {
        "global_similarity": global_similarity,
        "global_drift": global_drift,
        "top_k_drift": top_k_drift if top_k_drift is not None else global_drift,
        "unit_count": len(current_units),
        "comparison_unit_count": len(previous_units),
        "top_k_count": top_k_count,
        "top_changes": top_rows[:5],
        "aggregation": "top_k_sentence_drift",
        "unit_basis": "sentence",
    }


def _semantic_novelty_summary(
    current_chunks: Sequence[dict[str, Any]],
    previous_chunks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not current_chunks or not previous_chunks:
        return {
            "global_mean": None,
            "top_k_mean": None,
            "top_k_count": 0,
            "top_rows": [],
            "chunk_count": len(current_chunks),
            "comparison_chunk_count": len(previous_chunks),
            "aggregation": "top_k_chunk_novelty",
        }

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
    top_k_count = _top_k_count(len(novelty_rows))
    top_rows = novelty_rows[:top_k_count]
    return {
        "global_mean": mean_or_none(novelty_values),
        "top_k_mean": mean_or_none(row["novelty_distance"] for row in top_rows),
        "top_k_count": top_k_count,
        "top_rows": novelty_rows[:5],
        "chunk_count": len(current_chunks),
        "comparison_chunk_count": len(previous_chunks),
        "aggregation": "top_k_chunk_novelty",
    }


def _top_k_count(total_count: int) -> int:
    if total_count <= 0:
        return 0
    return min(total_count, max(DRIFT_TOPK_MIN_COUNT, int(ceil(total_count * DRIFT_TOPK_RATIO))))

def _is_forward_looking_text(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in FORWARD_LOOKING_KEYWORDS)
