from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from math import exp
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.news_item import NewsItem
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.catalog import get_signal_definition
from signals.common import clip01, coverage_ratio, weighted_average
from signals.policies import SENTIMENT_SIGNAL_WEIGHTS
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

SENTIMENT_SIGNAL_MODEL_VERSION = "sentiment_signals_v1"
SENTIMENT_LABEL_SCORES = {
    "positive": 0.5,
    "bullish": 0.5,
    "neutral": 0.0,
    "mixed": -0.1,
    "negative": -0.5,
    "bearish": -0.5,
}


@dataclass(slots=True)
class ComputedSentimentSignal:
    filing_id: int
    company_id: int
    signal_name: str
    signal_value: float | None
    detail: dict[str, Any]
    model_version: str = SENTIMENT_SIGNAL_MODEL_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_sentiment_signals(
    db: Session,
    *,
    filing_id: int,
    model_version: str = SENTIMENT_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    anchor_dt = datetime.combine(filing.filed_at, time.max, tzinfo=timezone.utc)
    ninety_days_ago = anchor_dt - timedelta(days=90)
    rows = db.scalars(
        select(NewsItem)
        .where(
            NewsItem.company_id == filing.company_id,
            NewsItem.published_at <= anchor_dt,
            NewsItem.published_at >= ninety_days_ago,
        )
        .order_by(NewsItem.published_at.asc(), NewsItem.id.asc())
    ).all()

    if not rows:
        signal_names = (
            "news_sentiment_signal",
            "news_volume_spike",
            "sentiment_signal",
        )
        return [
            _not_available_sentiment_signal(
                filing=filing,
                signal_name=signal_name,
                model_version=model_version,
                availability_reason="missing_news_items",
                extra_detail={"anchor_datetime": anchor_dt.isoformat()},
            ).to_dict()
            for signal_name in signal_names
        ]

    sentiment_value, sentiment_components = _news_sentiment_signal(anchor_dt=anchor_dt, rows=rows)
    volume_value, volume_components = _news_volume_spike(anchor_dt=anchor_dt, rows=rows)
    combined_value, combined_components = weighted_average(
        {
            "news_sentiment_signal": sentiment_value,
            "news_volume_spike": volume_value,
        },
        SENTIMENT_SIGNAL_WEIGHTS,
    )

    payloads = [
        ("news_sentiment_signal", sentiment_value, sentiment_components),
        ("news_volume_spike", volume_value, volume_components),
        ("sentiment_signal", combined_value, combined_components),
    ]

    signals: list[ComputedSentimentSignal] = []
    for signal_name, signal_value, component_scores in payloads:
        definition = get_signal_definition(signal_name)
        if signal_value is None:
            signals.append(
                _not_available_sentiment_signal(
                    filing=filing,
                    signal_name=signal_name,
                    model_version=model_version,
                    availability_reason="insufficient_news_signal_inputs",
                    extra_detail={
                        "description": definition.description if definition else "",
                        "anchor_datetime": anchor_dt.isoformat(),
                        "component_scores": component_scores,
                    },
                )
            )
            continue

        signals.append(
            ComputedSentimentSignal(
                filing_id=filing.id,
                company_id=filing.company_id,
                signal_name=signal_name,
                signal_value=signal_value,
                model_version=model_version,
                detail={
                    "description": definition.description if definition else "",
                    "anchor_datetime": anchor_dt.isoformat(),
                    "article_count_90d": len(rows),
                    "component_scores": component_scores,
                    "coverage_ratio": coverage_ratio(
                        component_scores,
                        expected_count=max(len(component_scores), 1),
                    ),
                    "confidence": _sentiment_confidence(
                        article_count=len(rows),
                        component_scores=component_scores,
                    ),
                    "signal_category": "sentiment",
                    "signal_role": "base" if signal_name != "sentiment_signal" else "composite_layer",
                    "model_version": model_version,
                },
            )
        )

    return [signal.to_dict() for signal in signals]


def compute_and_store_sentiment_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    model_version: str = SENTIMENT_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    if db is None:
        with get_db() as session:
            return compute_and_store_sentiment_signals(
                filing_id,
                db=session,
                model_version=model_version,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = compute_sentiment_signals(
        db,
        filing_id=filing_id,
        model_version=model_version,
    )
    upsert_signal_scores(db, signals)

    mark_signal_stage(filing, processing_status="sentiment_signal_scored")
    filing.last_error_message = None

    log_event(
        db,
        event_type="signal_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "sentiment_signals",
            "model_version": model_version,
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"] for signal in signals if signal["signal_value"] is None
            ],
        },
    )
    return signals


def _news_sentiment_signal(
    *,
    anchor_dt: datetime,
    rows: list[NewsItem],
) -> tuple[float | None, dict[str, float]]:
    sentiment_30d = _weighted_sentiment(anchor_dt=anchor_dt, rows=rows, days=30)
    sentiment_90d = _weighted_sentiment(anchor_dt=anchor_dt, rows=rows, days=90)
    if sentiment_30d is None or sentiment_90d is None:
        return None, {}

    sentiment_risk_30d = clip01((1.0 - sentiment_30d) / 2.0)
    sentiment_risk_90d = clip01((1.0 - sentiment_90d) / 2.0)
    deterioration = max(0.0, sentiment_risk_30d - sentiment_risk_90d)

    return clip01((0.60 * sentiment_risk_30d) + (0.40 * deterioration)), {
        "recent_sentiment_30d": sentiment_30d,
        "recent_sentiment_90d": sentiment_90d,
        "sentiment_risk_30d": sentiment_risk_30d,
        "sentiment_risk_90d": sentiment_risk_90d,
        "sentiment_deterioration": deterioration,
    }


def _news_volume_spike(
    *,
    anchor_dt: datetime,
    rows: list[NewsItem],
) -> tuple[float | None, dict[str, float]]:
    articles_this_week = sum(
        1
        for row in rows
        if _coerce_utc(row.published_at) >= anchor_dt - timedelta(days=7)
    )
    avg_weekly_articles_90d = len(rows) / 13.0

    if avg_weekly_articles_90d == 0.0:
        if articles_this_week == 0:
            return None, {}
        volume_ratio = float("inf")
        score = 1.0
    else:
        volume_ratio = articles_this_week / avg_weekly_articles_90d
        score = clip01((volume_ratio - 1.5) / 3.0)

    return score, {
        "articles_this_week": float(articles_this_week),
        "avg_weekly_articles_90d": avg_weekly_articles_90d,
        "volume_ratio": volume_ratio if volume_ratio != float("inf") else 99.0,
    }


def _weighted_sentiment(
    *,
    anchor_dt: datetime,
    rows: list[NewsItem],
    days: int,
) -> float | None:
    window_start = anchor_dt - timedelta(days=days)
    scored_values: list[float] = []
    weights: list[float] = []

    for row in rows:
        published_at = _coerce_utc(row.published_at)
        if published_at < window_start:
            continue
        score = _extract_sentiment_score(row)
        if score is None:
            continue
        days_ago = max((anchor_dt - published_at).days, 0)
        weight = exp(-days_ago / 15.0)
        scored_values.append(score * weight)
        weights.append(weight)

    if not weights:
        return None
    return float(sum(scored_values) / sum(weights))


def _extract_sentiment_score(row: NewsItem) -> float | None:
    if isinstance(row.raw_json, dict):
        raw_score = row.raw_json.get("sentiment_score")
        if isinstance(raw_score, (int, float)):
            return max(-1.0, min(1.0, float(raw_score)))

    label = (row.sentiment_label or "").strip().lower()
    if not label:
        return None
    return SENTIMENT_LABEL_SCORES.get(label)


def _sentiment_confidence(*, article_count: int, component_scores: dict[str, float]) -> float:
    article_ratio = clip01(article_count / 15.0)
    component_ratio = coverage_ratio(component_scores, expected_count=max(len(component_scores), 1))
    return clip01((0.65 * article_ratio) + (0.35 * component_ratio))


def _not_available_sentiment_signal(
    *,
    filing: Filing,
    signal_name: str,
    model_version: str,
    availability_reason: str,
    extra_detail: dict[str, Any],
) -> ComputedSentimentSignal:
    return ComputedSentimentSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=signal_name,
        signal_value=None,
        model_version=model_version,
        detail={
            "availability_reason": availability_reason,
            "coverage_ratio": 0.0,
            "confidence": 0.0,
            "signal_category": "sentiment",
            "signal_role": "base" if signal_name != "sentiment_signal" else "composite_layer",
            "model_version": model_version,
            **extra_detail,
        },
    )


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
