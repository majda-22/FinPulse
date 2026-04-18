from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.catalog import get_signal_definition
from signals.common import clip01, coverage_ratio, weighted_average
from signals.numeric_features import compute_numeric_feature_snapshot
from signals.policies import BALANCE_SHEET_STRESS_WEIGHTS, FUNDAMENTAL_MARGIN_WEIGHTS
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

NUMERIC_SIGNAL_MODEL_VERSION = "numeric_signals_v2"


@dataclass(slots=True)
class ComputedNumericSignal:
    filing_id: int
    company_id: int
    signal_name: str
    signal_value: float | None
    detail: dict[str, Any]
    model_version: str = NUMERIC_SIGNAL_MODEL_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_numeric_signals(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
    model_version: str = NUMERIC_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    snapshot = compute_numeric_feature_snapshot(
        db,
        filing_id=filing_id,
        history_limit=history_limit,
    )
    raw_facts = snapshot["raw_facts"]
    features = snapshot["features"]
    history_depth = len(snapshot.get("history_filing_ids", []))
    no_xbrl_facts = all(value is None for value in raw_facts.values())

    signal_builders = (
        ("fundamental_deterioration", _fundamental_deterioration),
        ("revenue_growth_deceleration", _revenue_growth_deceleration),
        ("balance_sheet_stress", _balance_sheet_stress),
        ("earnings_quality", _earnings_quality),
        ("numeric_anomaly", _numeric_anomaly),
    )

    signals: list[ComputedNumericSignal] = []
    for signal_name, builder in signal_builders:
        definition = get_signal_definition(signal_name)
        if no_xbrl_facts:
            signals.append(
                _not_available_numeric_signal(
                    filing=filing,
                    signal_name=signal_name,
                    model_version=model_version,
                    availability_reason="no_xbrl_facts",
                    feature_snapshot=snapshot,
                    extra_detail={"description": definition.description if definition else ""},
                )
            )
            continue

        signal_value, component_scores = builder(features)
        if signal_value is None:
            signals.append(
                _not_available_numeric_signal(
                    filing=filing,
                    signal_name=signal_name,
                    model_version=model_version,
                    availability_reason="insufficient_numeric_history",
                    feature_snapshot=snapshot,
                    extra_detail={
                        "description": definition.description if definition else "",
                        "component_scores": component_scores,
                        "history_depth": history_depth,
                    },
                )
            )
            continue

        signals.append(
            ComputedNumericSignal(
                filing_id=filing.id,
                company_id=filing.company_id,
                signal_name=signal_name,
                signal_value=signal_value,
                model_version=model_version,
                detail={
                    "description": definition.description if definition else "",
                    "coverage_ratio": coverage_ratio(component_scores, expected_count=max(len(component_scores), 1)),
                    "confidence": _numeric_confidence(history_depth=history_depth, component_scores=component_scores),
                    "history_depth": history_depth,
                    "feature_snapshot": snapshot,
                    "component_scores": component_scores,
                    "signal_category": "numbers",
                    "signal_role": "base",
                    "model_version": model_version,
                },
            )
        )

    return [signal.to_dict() for signal in signals]


def compute_xbrl_signals(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
    model_version: str = NUMERIC_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    return compute_numeric_signals(
        db,
        filing_id=filing_id,
        history_limit=history_limit,
        model_version=model_version,
    )


def compute_and_store_numeric_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    history_limit: int = 8,
    model_version: str = NUMERIC_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    if db is None:
        with get_db() as session:
            return compute_and_store_numeric_signals(
                filing_id,
                db=session,
                history_limit=history_limit,
                model_version=model_version,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = compute_numeric_signals(
        db,
        filing_id=filing_id,
        history_limit=history_limit,
        model_version=model_version,
    )
    upsert_signal_scores(db, signals)

    mark_signal_stage(filing, numeric_scored=True, processing_status="numeric_signal_scored")
    filing.last_error_message = None

    log_event(
        db,
        event_type="signal_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "numeric_signals",
            "model_version": model_version,
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"] for signal in signals if signal["signal_value"] is None
            ],
        },
    )
    return signals


def compute_and_store_xbrl_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    history_limit: int = 8,
    model_version: str = NUMERIC_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    return compute_and_store_numeric_signals(
        filing_id,
        db=db,
        history_limit=history_limit,
        model_version=model_version,
    )


def _fundamental_deterioration(features: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    components = {
        "gross_margin": _negative_delta_score(features.get("gross_margin_delta"), cap=0.20),
        "operating_margin": _negative_delta_score(features.get("operating_margin_delta"), cap=0.20),
        "net_margin": _negative_delta_score(features.get("net_margin_delta"), cap=0.20),
    }
    score, defined = weighted_average(components, FUNDAMENTAL_MARGIN_WEIGHTS)
    return score, defined


def _revenue_growth_deceleration(features: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    growth_current = features.get("revenue_growth_current")
    growth_prior = features.get("revenue_growth_prior")
    if growth_current is None or growth_prior is None:
        return None, {}

    deceleration = growth_prior - growth_current
    score = clip01(max(0.0, deceleration) / 0.30)
    return score, {"deceleration": deceleration}


def _balance_sheet_stress(features: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    components = {
        "leverage_score": _positive_shift_score(
            _delta(features.get("debt_to_equity_current"), features.get("debt_to_equity_prior")),
            cap=1.0,
        ),
        "cash_score": _positive_shift_score(
            _delta(features.get("cash_ratio_prior"), features.get("cash_ratio_current")),
            cap=0.10,
        ),
        "cf_quality_score": _cf_quality_score(features.get("cf_quality_current")),
    }
    score, defined = weighted_average(components, BALANCE_SHEET_STRESS_WEIGHTS)
    return score, defined


def _earnings_quality(features: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    accruals_ratio = features.get("accruals_ratio_current")
    if accruals_ratio is None:
        return None, {}
    score = clip01(max(0.0, accruals_ratio) / 0.10)
    return score, {"accruals_ratio": accruals_ratio}


def _numeric_anomaly(features: dict[str, float | None]) -> tuple[float | None, dict[str, float]]:
    anomaly_distance = features.get("numeric_anomaly_distance")
    if anomaly_distance is None:
        return None, {}
    score = clip01(anomaly_distance / 3.0)
    component_scores = {
        "gross_margin_zscore": features.get("gross_margin_zscore"),
        "operating_margin_zscore": features.get("operating_margin_zscore"),
        "revenue_growth_zscore": features.get("revenue_growth_zscore"),
        "debt_to_equity_zscore": features.get("debt_to_equity_zscore"),
        "anomaly_distance": anomaly_distance,
    }
    return score, {key: value for key, value in component_scores.items() if value is not None}


def _not_available_numeric_signal(
    *,
    filing: Filing,
    signal_name: str,
    model_version: str,
    availability_reason: str,
    feature_snapshot: dict[str, Any],
    extra_detail: dict[str, Any],
) -> ComputedNumericSignal:
    return ComputedNumericSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=signal_name,
        signal_value=None,
        model_version=model_version,
        detail={
            "availability_reason": availability_reason,
            "coverage_ratio": 0.0,
            "confidence": 0.0,
            "history_depth": len(feature_snapshot.get("history_filing_ids", [])),
            "feature_snapshot": feature_snapshot,
            "signal_category": "numbers",
            "signal_role": "base",
            "model_version": model_version,
            **extra_detail,
        },
    )


def _numeric_confidence(*, history_depth: int, component_scores: dict[str, float]) -> float:
    history_ratio = clip01(history_depth / 4.0)
    component_ratio = coverage_ratio(component_scores, expected_count=max(len(component_scores), 1))
    return clip01((0.6 * history_ratio) + (0.4 * component_ratio))


def _negative_delta_score(delta: float | None, *, cap: float) -> float | None:
    if delta is None:
        return None
    if delta >= 0:
        return 0.0
    return clip01(abs(delta) / cap)


def _positive_shift_score(value: float | None, *, cap: float) -> float | None:
    if value is None:
        return None
    return clip01(max(0.0, value) / cap)


def _cf_quality_score(cf_quality: float | None) -> float | None:
    if cf_quality is None:
        return None
    return clip01((1.0 - cf_quality) / 1.5)


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return float(current - previous)
