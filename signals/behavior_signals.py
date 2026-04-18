from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.signal_score import SignalScore
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.behavior_features import compute_behavior_feature_snapshot
from signals.catalog import get_signal_definition
from signals.common import clip01, coverage_ratio
from signals.policies import FORM4_GOVERNANCE_PENALTY_CAP, FORM4_GOVERNANCE_PENALTY_MULTIPLIER
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

BEHAVIOR_SIGNAL_MODEL_VERSION = "behavior_signals_v2"


@dataclass(slots=True)
class ComputedBehaviorSignal:
    filing_id: int
    company_id: int
    signal_name: str
    signal_value: float | None
    detail: dict[str, Any]
    model_version: str = BEHAVIOR_SIGNAL_MODEL_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_behavior_signals(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
    model_version: str = BEHAVIOR_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    snapshot = compute_behavior_feature_snapshot(
        db,
        filing_id=filing_id,
        history_limit=history_limit,
    )
    features = snapshot["features"]
    text_sentiment = _load_text_sentiment(db, filing_id=filing_id)

    ita_value, ita_components = _ita(features, text_sentiment)
    concentration_value, concentration_components = _insider_concentration(features)
    governance_penalty = min(
        FORM4_GOVERNANCE_PENALTY_CAP,
        float(features.get("late_filing_ratio") or 0.0) * FORM4_GOVERNANCE_PENALTY_MULTIPLIER,
    )
    insider_signal_value = clip01((0.70 * ita_value) + (0.30 * concentration_value) + governance_penalty)

    signal_payloads = [
        ("ita", ita_value, ita_components),
        ("insider_concentration", concentration_value, concentration_components),
        (
            "insider_signal",
            insider_signal_value,
            {
                "ita": ita_value,
                "insider_concentration": concentration_value,
                "governance_penalty": governance_penalty,
            },
        ),
    ]

    signals: list[ComputedBehaviorSignal] = []
    for signal_name, signal_value, component_scores in signal_payloads:
        definition = get_signal_definition(signal_name)
        signals.append(
            ComputedBehaviorSignal(
                filing_id=filing.id,
                company_id=filing.company_id,
                signal_name=signal_name,
                signal_value=signal_value,
                model_version=model_version,
                detail={
                    "description": definition.description if definition else "",
                    "feature_snapshot": snapshot,
                    "component_scores": component_scores,
                    "text_sentiment": text_sentiment,
                    "coverage_ratio": coverage_ratio(component_scores, expected_count=max(len(component_scores), 1)),
                    "confidence": _behavior_confidence(snapshot=snapshot, component_scores=component_scores),
                    "history_depth": len(snapshot.get("history_filing_ids", [])),
                    "signal_category": "behavior",
                    "signal_role": "base" if signal_name != "insider_signal" else "composite_layer",
                    "model_version": model_version,
                },
            )
        )

    return [signal.to_dict() for signal in signals]


def compute_insider_signals(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
    model_version: str = BEHAVIOR_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    return compute_behavior_signals(
        db,
        filing_id=filing_id,
        history_limit=history_limit,
        model_version=model_version,
    )


def compute_and_store_behavior_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    history_limit: int = 8,
    model_version: str = BEHAVIOR_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    if db is None:
        with get_db() as session:
            return compute_and_store_behavior_signals(
                filing_id,
                db=session,
                history_limit=history_limit,
                model_version=model_version,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = compute_behavior_signals(
        db,
        filing_id=filing_id,
        history_limit=history_limit,
        model_version=model_version,
    )
    upsert_signal_scores(db, signals)

    mark_signal_stage(filing, insider_scored=True, processing_status="insider_signal_scored")
    filing.last_error_message = None

    log_event(
        db,
        event_type="signal_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "behavior_signals",
            "model_version": model_version,
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"] for signal in signals if signal["signal_value"] is None
            ],
        },
    )
    return signals


def compute_and_store_insider_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    history_limit: int = 8,
    model_version: str = BEHAVIOR_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    return compute_and_store_behavior_signals(
        filing_id,
        db=db,
        history_limit=history_limit,
        model_version=model_version,
    )


def _ita(
    features: dict[str, Any],
    text_sentiment: float | None,
) -> tuple[float, dict[str, float]]:
    per_insider_activity = features.get("per_insider_activity", {}) or {}
    if not per_insider_activity:
        return 0.0, {"weighted_ita": 0.0}

    weighted_sum = 0.0
    total_weight = 0.0
    for insider_key, activity in per_insider_activity.items():
        sell_value = float(activity.get("opportunistic_sell_value") or 0.0)
        buy_value = float(activity.get("opportunistic_buy_value") or 0.0)
        total_value = sell_value + buy_value
        insider_ita = 0.0 if total_value == 0 else sell_value / total_value
        role_weight = float(activity.get("role_weight") or 0.0)
        weighted_sum += insider_ita * role_weight
        total_weight += role_weight

    weighted_ita = 0.0 if total_weight == 0 else weighted_sum / total_weight
    ita_final = weighted_ita
    if (text_sentiment or 0.0) > 0.6 and weighted_ita > 0.6:
        ita_final = clip01(weighted_ita * 1.25)

    return ita_final, {
        "weighted_ita": weighted_ita,
        "amplified_ita": ita_final,
        "opportunistic_sell_value": float(features.get("opportunistic_sell_value") or 0.0),
        "opportunistic_buy_value": float(features.get("opportunistic_buy_value") or 0.0),
    }


def _insider_concentration(features: dict[str, Any]) -> tuple[float, dict[str, float]]:
    unique_sellers = int(features.get("unique_sellers_in_window") or 0)
    if unique_sellers >= 4:
        score = 1.0
    elif unique_sellers == 3:
        score = 0.75
    elif unique_sellers == 2:
        score = 0.50
    elif unique_sellers == 1:
        score = 0.25
    else:
        score = 0.0
    return score, {"unique_sellers_in_window": float(unique_sellers)}


def _load_text_sentiment(db: Session, *, filing_id: int) -> float | None:
    row = db.scalar(
        select(SignalScore)
        .where(
            SignalScore.filing_id == filing_id,
            SignalScore.signal_name == "text_sentiment",
        )
        .order_by(SignalScore.computed_at.desc(), SignalScore.id.desc())
        .limit(1)
    )
    return None if row is None else row.signal_value


def _behavior_confidence(*, snapshot: dict[str, Any], component_scores: dict[str, float]) -> float:
    history_depth = len(snapshot.get("history_filing_ids", []))
    active_insiders = int(snapshot["features"].get("active_insider_count") or 0)
    history_ratio = clip01(history_depth / 4.0)
    activity_ratio = clip01(active_insiders / 3.0)
    component_ratio = coverage_ratio(component_scores, expected_count=max(len(component_scores), 1))
    return clip01((0.35 * history_ratio) + (0.35 * activity_ratio) + (0.30 * component_ratio))
