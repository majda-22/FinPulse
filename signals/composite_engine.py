from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.signal_score import SignalScore
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.catalog import get_signal_definition
from signals.composite_repo import load_signal_rows_by_name
from signals.common import clip01
from signals.history import ANNUAL_FORMS
from signals.nci_repo import upsert_nci_score
from signals.policies import (
    CONVERGENCE_THRESHOLDS,
    CONVERGENCE_TIERS,
    NCI_COVERAGE_HIGH,
    NCI_COVERAGE_MEDIUM,
    NCI_WEIGHTS,
)
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

COMPOSITE_SIGNAL_MODEL_VERSION = "nci_composite_v2"

LOW_LEVEL_SIGNAL_NAMES = (
    "rlds",
    "mda_drift",
    "forward_pessimism",
    "text_sentiment",
    "fundamental_deterioration",
    "revenue_growth_deceleration",
    "balance_sheet_stress",
    "earnings_quality",
    "numeric_anomaly",
    "insider_signal",
    "market_signal",
    "sentiment_signal",
)
TOTAL_DECLARED_NCI_WEIGHT = float(sum(NCI_WEIGHTS.values()))


@dataclass(slots=True)
class ComputedCompositeSignal:
    filing_id: int
    company_id: int
    signal_name: str
    signal_value: float | None
    detail: dict[str, Any]
    model_version: str = COMPOSITE_SIGNAL_MODEL_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_composite_signals(
    db: Session,
    *,
    filing_id: int,
    model_version: str = COMPOSITE_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signal_rows = load_signal_rows_by_name(
        db,
        filing_id=filing_id,
        signal_names=LOW_LEVEL_SIGNAL_NAMES,
    )
    signal_values = {
        signal_name: row.signal_value
        for signal_name, row in signal_rows.items()
    }

    divergence = _build_divergence_signal(
        filing=filing,
        model_version=model_version,
        text_sentiment=signal_values.get("text_sentiment"),
        fundamental_deterioration=signal_values.get("fundamental_deterioration"),
    )
    convergence = _build_convergence_signal(
        filing=filing,
        model_version=model_version,
        signal_values=signal_values,
    )
    nci_global = _build_nci_signal(
        filing=filing,
        model_version=model_version,
        signal_values=signal_values,
        convergence=convergence,
        source_rows=signal_rows,
    )
    composite_alias = _build_alias_signal(
        filing=filing,
        model_version=model_version,
        alias_name="composite_filing_risk",
        target_name="nci_global",
        target_value=nci_global.signal_value,
    )

    return [
        divergence.to_dict(),
        convergence.to_dict(),
        nci_global.to_dict(),
        composite_alias.to_dict(),
    ]


def compute_and_store_composite_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    model_version: str = COMPOSITE_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    if db is None:
        with get_db() as session:
            return compute_and_store_composite_signals(
                filing_id,
                db=session,
                model_version=model_version,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = compute_composite_signals(
        db,
        filing_id=filing_id,
        model_version=model_version,
    )
    stored_rows = upsert_signal_scores(db, signals)
    all_rows = load_signal_rows_by_name(
        db,
        filing_id=filing_id,
        signal_names=LOW_LEVEL_SIGNAL_NAMES + ("convergence_signal", "narrative_numeric_divergence"),
    )

    signal_rows_by_name = {row.signal_name: row for row in stored_rows}
    nci_row = signal_rows_by_name.get("nci_global")
    convergence_row = signal_rows_by_name.get("convergence_signal")
    rlds_row = all_rows.get("rlds")
    signal_values = {
        name: (row.signal_value if row is not None else None)
        for name, row in all_rows.items()
    }

    if nci_row is not None and nci_row.signal_value is not None:
        top_anomalous_paragraphs = None
        if rlds_row is not None and isinstance(rlds_row.detail, dict):
            top_anomalous_paragraphs = rlds_row.detail.get("top_novel_paragraphs")

        nci_detail = nci_row.detail if isinstance(nci_row.detail, dict) else {}
        convergence_detail = convergence_row.detail if convergence_row is not None and isinstance(convergence_row.detail, dict) else {}
        coverage_ratio_value = _safe_float(nci_detail.get("coverage_ratio"))
        confidence_label = str(nci_detail.get("confidence_label") or _coverage_confidence_label(coverage_ratio_value))
        data_fresh = confidence_label != "low"

        upsert_nci_score(
            db,
            company_id=filing.company_id,
            filing_id=filing.id,
            signal_score_id=nci_row.id,
            nci_global=float(nci_row.signal_value),
            model_version=model_version,
            event_type=_infer_nci_event_type(filing),
            fiscal_year=filing.fiscal_year,
            fiscal_quarter=filing.fiscal_quarter,
            convergence_tier=str(convergence_detail.get("tier") or "none"),
            layers_elevated=_safe_int(convergence_detail.get("layers_elevated")),
            confidence=confidence_label,
            coverage_ratio=coverage_ratio_value,
            signal_text=_safe_float(signal_values.get("rlds")),
            signal_mda=_safe_float(signal_values.get("mda_drift")),
            signal_pessimism=_safe_float(signal_values.get("forward_pessimism")),
            signal_fundamental=_safe_float(signal_values.get("fundamental_deterioration")),
            signal_balance=_safe_float(signal_values.get("balance_sheet_stress")),
            signal_growth=_safe_float(signal_values.get("revenue_growth_deceleration")),
            signal_earnings=_safe_float(signal_values.get("earnings_quality")),
            signal_anomaly=_safe_float(signal_values.get("numeric_anomaly")),
            signal_insider=_safe_float(signal_values.get("insider_signal")),
            signal_market=_safe_float(signal_values.get("market_signal")),
            signal_sentiment=_safe_float(signal_values.get("sentiment_signal")),
            text_source_filing=filing.id,
            xbrl_source_filing=filing.id,
            text_staleness_days=0,
            data_fresh=data_fresh,
            staleness_reason=None if data_fresh else "low_signal_coverage",
            top_anomalous_paragraphs=top_anomalous_paragraphs,
            computed_at=nci_row.computed_at,
        )

    mark_signal_stage(filing, composite_scored=True, processing_status="composite_scored")
    filing.last_error_message = None

    log_event(
        db,
        event_type="composite_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "composite_engine",
            "model_version": model_version,
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"] for signal in signals if signal["signal_value"] is None
            ],
        },
    )
    return signals


def _build_divergence_signal(
    *,
    filing: Filing,
    model_version: str,
    text_sentiment: float | None,
    fundamental_deterioration: float | None,
) -> ComputedCompositeSignal:
    definition = get_signal_definition("narrative_numeric_divergence")
    if text_sentiment is None or fundamental_deterioration is None:
        return _not_available_composite_signal(
            filing=filing,
            signal_name="narrative_numeric_divergence",
            model_version=model_version,
            availability_reason="missing_required_inputs",
            extra_detail={"description": definition.description if definition else ""},
        )

    numeric_health = 1.0 - fundamental_deterioration
    signal_value = abs(text_sentiment - numeric_health)
    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="narrative_numeric_divergence",
        signal_value=clip01(signal_value),
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "text_sentiment": text_sentiment,
            "numeric_health": numeric_health,
            "signal_category": "composite",
            "signal_role": "diagnostic",
            "coverage_ratio": 1.0,
            "confidence": 1.0,
            "model_version": model_version,
        },
    )


def _build_convergence_signal(
    *,
    filing: Filing,
    model_version: str,
    signal_values: dict[str, float | None],
) -> ComputedCompositeSignal:
    definition = get_signal_definition("convergence_signal")
    layer_scores = {
        "text": _layer_max(signal_values, "rlds", "forward_pessimism"),
        "numeric": _layer_max(signal_values, "fundamental_deterioration", "balance_sheet_stress"),
        "behavior": signal_values.get("insider_signal"),
        "market": signal_values.get("market_signal"),
        "sentiment": signal_values.get("sentiment_signal"),
    }
    elevated_layers = [
        layer
        for layer, score in layer_scores.items()
        if score is not None and score >= CONVERGENCE_THRESHOLDS[layer]
    ]
    layers_elevated = len(elevated_layers)
    tier, boost = CONVERGENCE_TIERS.get(layers_elevated, ("none", 0.0))

    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="convergence_signal",
        signal_value=boost,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "thresholds": dict(CONVERGENCE_THRESHOLDS),
            "layer_scores": layer_scores,
            "elevated_layers": elevated_layers,
            "layers_elevated": layers_elevated,
            "tier": tier,
            "boost": boost,
            "coverage_ratio": _defined_layer_ratio(layer_scores),
            "confidence": _defined_layer_ratio(layer_scores),
            "signal_category": "composite",
            "signal_role": "derived",
            "model_version": model_version,
        },
    )


def _build_nci_signal(
    *,
    filing: Filing,
    model_version: str,
    signal_values: dict[str, float | None],
    convergence: ComputedCompositeSignal,
    source_rows: dict[str, SignalScore],
) -> ComputedCompositeSignal:
    definition = get_signal_definition("nci_global")
    inputs = {
        "rlds": signal_values.get("rlds"),
        "mda_drift": signal_values.get("mda_drift"),
        "forward_pessimism": signal_values.get("forward_pessimism"),
        "fundamental_deterioration": signal_values.get("fundamental_deterioration"),
        "balance_sheet_stress": signal_values.get("balance_sheet_stress"),
        "revenue_growth_deceleration": signal_values.get("revenue_growth_deceleration"),
        "earnings_quality": signal_values.get("earnings_quality"),
        "numeric_anomaly": signal_values.get("numeric_anomaly"),
        "insider_signal": signal_values.get("insider_signal"),
        "market_signal": signal_values.get("market_signal"),
        "sentiment_signal": signal_values.get("sentiment_signal"),
    }
    active_weights = {
        name: weight
        for name, weight in NCI_WEIGHTS.items()
        if inputs.get(name) is not None
    }
    available_weight = float(sum(active_weights.values()))
    if available_weight == 0.0:
        return _not_available_composite_signal(
            filing=filing,
            signal_name="nci_global",
            model_version=model_version,
            availability_reason="missing_all_component_inputs",
            extra_detail={
                "description": definition.description if definition else "",
                "inputs": inputs,
            },
        )

    weighted_sum = sum((inputs[name] or 0.0) * weight for name, weight in active_weights.items())
    raw_score = weighted_sum if available_weight >= 1.0 else (weighted_sum / available_weight)
    convergence_boost = float(convergence.signal_value or 0.0)
    boosted_score = clip01(raw_score + convergence_boost)

    confidence_scores = []
    for name in active_weights:
        row = source_rows.get(name)
        if row is None or not isinstance(row.detail, dict):
            continue
        confidence = row.detail.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence_scores.append(float(confidence))

    confidence_score = (sum(confidence_scores) / len(confidence_scores)) if confidence_scores else None
    normalized_coverage = clip01(available_weight)
    confidence_label = _coverage_confidence_label(normalized_coverage)

    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="nci_global",
        signal_value=boosted_score,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "inputs": inputs,
            "weights": dict(NCI_WEIGHTS),
            "active_weights": active_weights,
            "coverage_ratio": normalized_coverage,
            "confidence": confidence_score,
            "confidence_label": confidence_label,
            "raw_score": raw_score,
            "convergence_boost": convergence_boost,
            "convergence_tier": convergence.detail.get("tier") if isinstance(convergence.detail, dict) else None,
            "layers_elevated": convergence.detail.get("layers_elevated") if isinstance(convergence.detail, dict) else None,
            "declared_weight_total": TOTAL_DECLARED_NCI_WEIGHT,
            "signal_category": "composite",
            "signal_role": "final",
            "model_version": model_version,
        },
    )


def _build_alias_signal(
    *,
    filing: Filing,
    model_version: str,
    alias_name: str,
    target_name: str,
    target_value: float | None,
) -> ComputedCompositeSignal:
    definition = get_signal_definition(alias_name)
    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=alias_name,
        signal_value=target_value,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "alias_of": target_name,
            "signal_category": "composite",
            "signal_role": "final_alias",
            "model_version": model_version,
        },
    )


def _not_available_composite_signal(
    *,
    filing: Filing,
    signal_name: str,
    model_version: str,
    availability_reason: str,
    extra_detail: dict[str, Any],
) -> ComputedCompositeSignal:
    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=signal_name,
        signal_value=None,
        model_version=model_version,
        detail={
            "availability_reason": availability_reason,
            "coverage_ratio": 0.0,
            "confidence": 0.0,
            "signal_category": "composite",
            "signal_role": "derived" if signal_name != "nci_global" else "final",
            "model_version": model_version,
            **extra_detail,
        },
    )


def _layer_max(signal_values: dict[str, float | None], *signal_names: str) -> float | None:
    candidates = [signal_values.get(name) for name in signal_names if signal_values.get(name) is not None]
    if not candidates:
        return None
    return max(float(value) for value in candidates)


def _defined_layer_ratio(layer_scores: dict[str, float | None]) -> float:
    defined = sum(1 for value in layer_scores.values() if value is not None)
    return defined / max(len(layer_scores), 1)


def _coverage_confidence_label(coverage_ratio: float | None) -> str:
    if coverage_ratio is None:
        return "low"
    if coverage_ratio >= NCI_COVERAGE_HIGH:
        return "high"
    if coverage_ratio >= NCI_COVERAGE_MEDIUM:
        return "medium"
    return "low"


def _infer_nci_event_type(filing: Filing) -> str:
    if filing.form_type in ANNUAL_FORMS:
        return "annual_anchor"
    return "quarterly_update"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
