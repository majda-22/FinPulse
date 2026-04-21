from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import exp
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.signal_score import SignalScore
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.catalog import get_signal_definition
from signals.composite_repo import load_signal_rows_by_name
from signals.common import clip01
from signals.history import ANNUAL_FORMS, QUARTERLY_FORMS
from signals.nci_repo import upsert_nci_score
from signals.policies import (
    CARRY_FORWARD_LOOKBACK_FILINGS,
    CARRY_FORWARD_STALENESS_PENALTY,
    CONVERGENCE_THRESHOLDS,
    CONVERGENCE_TIERS,
    NCI_COVERAGE_HIGH,
    NCI_COVERAGE_MEDIUM,
    NCI_CRITICAL_LAYER_SIGNALS,
    NCI_MIN_REQUIRED_COVERAGE,
    NCI_NORMALIZATION_HISTORY_MIN_COUNT,
    NCI_WEIGHTS,
)
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

COMPOSITE_SIGNAL_MODEL_VERSION = "nci_composite_v4"
SCORING_NCI_SIGNAL_NAMES = tuple(
    signal_name
    for signal_name, weight in NCI_WEIGHTS.items()
    if weight > 0.0
)

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
COMPOSITE_INPUT_SIGNAL_NAMES = tuple(NCI_WEIGHTS.keys())
TEXT_INPUT_SIGNAL_NAMES = ("rlds", "mda_drift", "forward_pessimism")
NUMERIC_INPUT_SIGNAL_NAMES = (
    "fundamental_deterioration",
    "balance_sheet_stress",
    "revenue_growth_deceleration",
    "earnings_quality",
    "numeric_anomaly",
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


@dataclass(slots=True)
class ResolvedSignalInput:
    signal_name: str
    value: float | None
    raw_value: float | None
    source_filing_id: int | None
    carried_forward: bool
    filings_back: int = 0
    staleness_penalty: float = 1.0
    confidence: float | None = None
    source_row: SignalScore | None = None
    source_filed_at: Any | None = None


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
    resolved_inputs = _resolve_composite_inputs(
        db,
        filing=filing,
        signal_rows=signal_rows,
    )
    signal_values = {
        signal_name: resolution.value
        for signal_name, resolution in resolved_inputs.items()
    }

    divergence = _build_divergence_signal(
        filing=filing,
        model_version=model_version,
        forward_pessimism=signal_values.get("forward_pessimism"),
        fundamental_deterioration=signal_values.get("fundamental_deterioration"),
    )
    convergence = _build_convergence_signal(
        filing=filing,
        model_version=model_version,
        signal_values=signal_values,
    )
    nci_global = _build_nci_signal(
        db=db,
        filing=filing,
        model_version=model_version,
        signal_values=signal_values,
        convergence=convergence,
        input_resolutions=resolved_inputs,
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

    if nci_row is not None and nci_row.signal_value is not None:
        nci_detail = nci_row.detail if isinstance(nci_row.detail, dict) else {}
        convergence_detail = convergence_row.detail if convergence_row is not None and isinstance(convergence_row.detail, dict) else {}
        coverage_ratio_value = _safe_float(nci_detail.get("coverage_ratio"))
        confidence_label = str(nci_detail.get("confidence_label") or _coverage_confidence_label(coverage_ratio_value))
        data_fresh = confidence_label != "low"
        effective_inputs = nci_detail.get("effective_inputs") if isinstance(nci_detail.get("effective_inputs"), dict) else {}
        top_anomalous_paragraphs = nci_detail.get("top_anomalous_paragraphs")
        carried_forward_inputs = nci_detail.get("carried_forward_inputs")
        staleness_reason = None
        if isinstance(carried_forward_inputs, dict) and carried_forward_inputs:
            staleness_reason = "carried_forward_inputs"

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
            signal_text=_safe_float(effective_inputs.get("rlds")),
            signal_mda=_safe_float(effective_inputs.get("mda_drift")),
            signal_pessimism=_safe_float(effective_inputs.get("forward_pessimism")),
            signal_fundamental=_safe_float(effective_inputs.get("fundamental_deterioration")),
            signal_balance=_safe_float(effective_inputs.get("balance_sheet_stress")),
            signal_growth=_safe_float(effective_inputs.get("revenue_growth_deceleration")),
            signal_earnings=_safe_float(effective_inputs.get("earnings_quality")),
            signal_anomaly=_safe_float(effective_inputs.get("numeric_anomaly")),
            signal_insider=_safe_float(effective_inputs.get("insider_signal")),
            signal_market=_safe_float(effective_inputs.get("market_signal")),
            signal_sentiment=_safe_float(effective_inputs.get("sentiment_signal")),
            text_source_filing=_safe_int(nci_detail.get("text_source_filing")),
            xbrl_source_filing=_safe_int(nci_detail.get("xbrl_source_filing")),
            text_staleness_days=_safe_int(nci_detail.get("text_staleness_days")),
            data_fresh=data_fresh,
            staleness_reason=staleness_reason if data_fresh else "low_signal_coverage",
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
    forward_pessimism: float | None,
    fundamental_deterioration: float | None,
) -> ComputedCompositeSignal:
    definition = get_signal_definition("narrative_numeric_divergence")
    if forward_pessimism is None or fundamental_deterioration is None:
        return _not_available_composite_signal(
            filing=filing,
            signal_name="narrative_numeric_divergence",
            model_version=model_version,
            availability_reason="missing_required_inputs",
            extra_detail={"description": definition.description if definition else ""},
        )

    narrative_risk = clip01(forward_pessimism)
    numeric_risk = clip01(fundamental_deterioration)
    narrative_health = clip01(1.0 - narrative_risk)
    numeric_health = 1.0 - fundamental_deterioration
    signal_value = abs(narrative_risk - numeric_risk)
    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="narrative_numeric_divergence",
        signal_value=clip01(signal_value),
        model_version=model_version,
        detail={
            "description": definition.description if definition else "",
            "tone_basis": "forward_pessimism",
            "forward_pessimism": narrative_risk,
            "narrative_risk": narrative_risk,
            "narrative_health": narrative_health,
            "numeric_risk": numeric_risk,
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
    db: Session,
    filing: Filing,
    model_version: str,
    signal_values: dict[str, float | None],
    convergence: ComputedCompositeSignal,
    input_resolutions: dict[str, ResolvedSignalInput],
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
    expected_signal_names = SCORING_NCI_SIGNAL_NAMES
    available_signal_names = [
        name
        for name in expected_signal_names
        if inputs.get(name) is not None
    ]
    missing_signal_names = [
        name
        for name in expected_signal_names
        if inputs.get(name) is None
    ]
    available_signal_count = len(available_signal_names)
    expected_signal_count = len(expected_signal_names)
    normalized_coverage = clip01(available_signal_count / max(expected_signal_count, 1))
    missing_critical_layers = _missing_critical_layers(inputs)

    active_weights = {
        name: weight
        for name, weight in NCI_WEIGHTS.items()
        if weight > 0.0
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
                "expected_signal_count": expected_signal_count,
                "available_signal_count": available_signal_count,
                "available_signal_names": available_signal_names,
                "missing_signal_names": missing_signal_names,
                "missing_critical_layers": missing_critical_layers,
            },
        )

    if normalized_coverage < NCI_MIN_REQUIRED_COVERAGE:
        return _not_available_composite_signal(
            filing=filing,
            signal_name="nci_global",
            model_version=model_version,
            availability_reason="insufficient_signal_coverage",
            extra_detail={
                "description": definition.description if definition else "",
                "inputs": inputs,
                "weights": dict(NCI_WEIGHTS),
                "active_weights": active_weights,
                "coverage_ratio": normalized_coverage,
                "confidence_label": "low",
                "expected_signal_count": expected_signal_count,
                "available_signal_count": available_signal_count,
                "available_signal_names": available_signal_names,
                "missing_signal_names": missing_signal_names,
                "missing_critical_layers": missing_critical_layers,
            },
        )

    weighted_sum = sum((inputs[name] or 0.0) * weight for name, weight in active_weights.items())
    raw_score = (
        weighted_sum
        if available_weight >= TOTAL_DECLARED_NCI_WEIGHT
        else ((weighted_sum / available_weight) * TOTAL_DECLARED_NCI_WEIGHT)
    )
    convergence_boost = float(convergence.signal_value or 0.0)
    raw_total = raw_score + convergence_boost
    normalization = _normalize_nci_value(
        db,
        raw_total=raw_total,
        model_version=model_version,
        current_filing_id=filing.id,
    )
    boosted_score = float(normalization["value"])

    confidence_scores = []
    for name in active_weights:
        resolution = input_resolutions.get(name)
        if resolution is None or resolution.source_row is None:
            continue
        confidence = resolution.confidence
        if confidence is not None:
            confidence_scores.append(float(confidence))

    confidence_score = (sum(confidence_scores) / len(confidence_scores)) if confidence_scores else None
    confidence_label = _coverage_confidence_label(normalized_coverage)
    confidence_label = _downgrade_confidence_for_missing_critical_layers(
        confidence_label,
        missing_critical_layers=missing_critical_layers,
    )
    carried_forward_inputs = _carried_forward_input_detail(input_resolutions)
    top_anomalous_paragraphs = _resolved_top_anomalous_paragraphs(input_resolutions.get("rlds"))
    text_source_filing = _group_source_filing_id(input_resolutions, TEXT_INPUT_SIGNAL_NAMES, fallback=filing.id)
    xbrl_source_filing = _group_source_filing_id(input_resolutions, NUMERIC_INPUT_SIGNAL_NAMES, fallback=filing.id)
    text_staleness_days = _group_staleness_days(filing, input_resolutions, TEXT_INPUT_SIGNAL_NAMES)

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
            "expected_signal_count": expected_signal_count,
            "available_signal_count": available_signal_count,
            "available_signal_names": available_signal_names,
            "missing_signal_names": missing_signal_names,
            "missing_critical_layers": missing_critical_layers,
            "raw_score": raw_score,
            "raw_total_before_normalization": raw_total,
            "convergence_boost": convergence_boost,
            "normalization_method": normalization["method"],
            "normalization_reference_count": normalization["history_count"],
            "normalization_mean": normalization.get("mean"),
            "normalization_std": normalization.get("std"),
            "normalized_score": boosted_score,
            "convergence_tier": convergence.detail.get("tier") if isinstance(convergence.detail, dict) else None,
            "layers_elevated": convergence.detail.get("layers_elevated") if isinstance(convergence.detail, dict) else None,
            "effective_inputs": {
                name: value
                for name, value in inputs.items()
                if value is not None
            },
            "carried_forward_inputs": carried_forward_inputs,
            "text_source_filing": text_source_filing,
            "xbrl_source_filing": xbrl_source_filing,
            "text_staleness_days": text_staleness_days,
            "top_anomalous_paragraphs": top_anomalous_paragraphs,
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


def _resolve_composite_inputs(
    db: Session,
    *,
    filing: Filing,
    signal_rows: dict[str, SignalScore],
) -> dict[str, ResolvedSignalInput]:
    previous_filings = _load_previous_anchor_filings(
        db,
        filing=filing,
        lookback=CARRY_FORWARD_LOOKBACK_FILINGS,
    )
    previous_signal_maps = [
        load_signal_rows_by_name(
            db,
            filing_id=previous_filing.id,
            signal_names=COMPOSITE_INPUT_SIGNAL_NAMES,
        )
        for previous_filing in previous_filings
    ]

    resolved: dict[str, ResolvedSignalInput] = {}
    for signal_name in COMPOSITE_INPUT_SIGNAL_NAMES:
        current_row = signal_rows.get(signal_name)
        if current_row is not None and current_row.signal_value is not None:
            resolved[signal_name] = _resolved_input_from_row(
                signal_name,
                current_row,
                source_filing_id=filing.id,
                source_filed_at=filing.filed_at,
                carried_forward=False,
                filings_back=0,
                staleness_penalty=1.0,
            )
            continue

        fallback_resolution = ResolvedSignalInput(
            signal_name=signal_name,
            value=None,
            raw_value=None,
            source_filing_id=filing.id if current_row is not None else None,
            carried_forward=False,
            source_row=current_row,
            source_filed_at=filing.filed_at if current_row is not None else None,
            confidence=_signal_confidence(current_row),
        )
        for filings_back, previous_filing in enumerate(previous_filings, start=1):
            previous_row = previous_signal_maps[filings_back - 1].get(signal_name)
            if previous_row is None or previous_row.signal_value is None:
                continue
            fallback_resolution = _resolved_input_from_row(
                signal_name,
                previous_row,
                source_filing_id=previous_filing.id,
                source_filed_at=previous_filing.filed_at,
                carried_forward=True,
                filings_back=filings_back,
                staleness_penalty=CARRY_FORWARD_STALENESS_PENALTY,
            )
            break
        resolved[signal_name] = fallback_resolution

    return resolved


def _resolved_input_from_row(
    signal_name: str,
    row: SignalScore,
    *,
    source_filing_id: int,
    source_filed_at: Any,
    carried_forward: bool,
    filings_back: int,
    staleness_penalty: float,
) -> ResolvedSignalInput:
    raw_value = float(row.signal_value) if row.signal_value is not None else None
    value = raw_value
    confidence = _signal_confidence(row)
    if carried_forward and raw_value is not None:
        value = clip01(raw_value * staleness_penalty)
        if confidence is not None:
            confidence = clip01(confidence * staleness_penalty)
    return ResolvedSignalInput(
        signal_name=signal_name,
        value=value,
        raw_value=raw_value,
        source_filing_id=source_filing_id,
        carried_forward=carried_forward,
        filings_back=filings_back,
        staleness_penalty=staleness_penalty,
        confidence=confidence,
        source_row=row,
        source_filed_at=source_filed_at,
    )


def _signal_confidence(row: SignalScore | None) -> float | None:
    if row is None or not isinstance(row.detail, dict):
        return None
    confidence = row.detail.get("confidence")
    if isinstance(confidence, (int, float)):
        return float(confidence)
    return None


def _load_previous_anchor_filings(
    db: Session,
    *,
    filing: Filing,
    lookback: int,
) -> list[Filing]:
    anchor_forms = tuple(sorted(ANNUAL_FORMS | QUARTERLY_FORMS))
    return db.scalars(
        select(Filing)
        .where(
            Filing.company_id == filing.company_id,
            Filing.form_type.in_(anchor_forms),
            or_(
                Filing.filed_at < filing.filed_at,
                and_(Filing.filed_at == filing.filed_at, Filing.id < filing.id),
            ),
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(lookback)
    ).all()


def _carried_forward_input_detail(
    input_resolutions: dict[str, ResolvedSignalInput],
) -> dict[str, dict[str, Any]]:
    detail: dict[str, dict[str, Any]] = {}
    for signal_name, resolution in input_resolutions.items():
        if not resolution.carried_forward or resolution.value is None:
            continue
        detail[signal_name] = {
            "source_filing_id": resolution.source_filing_id,
            "filings_back": resolution.filings_back,
            "staleness_penalty": resolution.staleness_penalty,
            "raw_value": resolution.raw_value,
            "adjusted_value": resolution.value,
        }
    return detail


def _group_source_filing_id(
    input_resolutions: dict[str, ResolvedSignalInput],
    signal_names: tuple[str, ...],
    *,
    fallback: int,
) -> int:
    source_ids = [
        resolution.source_filing_id
        for signal_name, resolution in input_resolutions.items()
        if signal_name in signal_names and resolution.value is not None and resolution.source_filing_id is not None
    ]
    if not source_ids:
        return fallback
    return max(source_ids)


def _group_staleness_days(
    filing: Filing,
    input_resolutions: dict[str, ResolvedSignalInput],
    signal_names: tuple[str, ...],
) -> int:
    stale_days = []
    for signal_name, resolution in input_resolutions.items():
        if signal_name not in signal_names or resolution.source_filed_at is None:
            continue
        stale_days.append((filing.filed_at - resolution.source_filed_at).days)
    if not stale_days:
        return 0
    return max(stale_days)


def _resolved_top_anomalous_paragraphs(
    resolution: ResolvedSignalInput | None,
) -> dict[str, Any] | list[Any] | None:
    if resolution is None or resolution.source_row is None or not isinstance(resolution.source_row.detail, dict):
        return None
    return resolution.source_row.detail.get("top_novel_paragraphs")


def _normalize_nci_value(
    db: Session,
    *,
    raw_total: float,
    model_version: str,
    current_filing_id: int,
) -> dict[str, Any]:
    history_raw_scores = _load_historical_raw_nci_values(
        db,
        model_version=model_version,
        current_filing_id=current_filing_id,
    )
    if len(history_raw_scores) >= NCI_NORMALIZATION_HISTORY_MIN_COUNT:
        mean_value = sum(history_raw_scores) / len(history_raw_scores)
        variance = sum((score - mean_value) ** 2 for score in history_raw_scores) / len(history_raw_scores)
        std_value = variance ** 0.5
        if std_value > 0.0:
            z_score = (raw_total - mean_value) / std_value
            return {
                "value": clip01(1.0 / (1.0 + exp(-z_score))),
                "method": "zscore_sigmoid",
                "history_count": len(history_raw_scores),
                "mean": mean_value,
                "std": std_value,
            }

    return {
        "value": clip01(raw_total),
        "method": "identity",
        "history_count": len(history_raw_scores),
        "mean": None,
        "std": None,
    }


def _load_historical_raw_nci_values(
    db: Session,
    *,
    model_version: str,
    current_filing_id: int,
) -> list[float]:
    rows = db.scalars(
        select(SignalScore)
        .where(
            SignalScore.signal_name == "nci_global",
            SignalScore.filing_id != current_filing_id,
            SignalScore.model_version == model_version,
            SignalScore.signal_value.is_not(None),
        )
        .order_by(SignalScore.computed_at.desc(), SignalScore.id.desc())
    ).all()

    history: list[float] = []
    for row in rows:
        if not isinstance(row.detail, dict):
            continue
        raw_total = row.detail.get("raw_total_before_normalization")
        if isinstance(raw_total, (int, float)):
            history.append(float(raw_total))
            continue
        raw_score = row.detail.get("raw_score")
        convergence_boost = row.detail.get("convergence_boost")
        if isinstance(raw_score, (int, float)):
            history.append(float(raw_score) + float(convergence_boost or 0.0))
    return history


def _defined_layer_ratio(layer_scores: dict[str, float | None]) -> float:
    defined = sum(1 for value in layer_scores.values() if value is not None)
    return defined / max(len(layer_scores), 1)


def _missing_critical_layers(inputs: dict[str, float | None]) -> list[str]:
    return [
        layer_name
        for layer_name, signal_names in NCI_CRITICAL_LAYER_SIGNALS.items()
        if not any(inputs.get(signal_name) is not None for signal_name in signal_names)
    ]


def _downgrade_confidence_for_missing_critical_layers(
    confidence_label: str,
    *,
    missing_critical_layers: list[str],
) -> str:
    if not missing_critical_layers:
        return confidence_label
    if confidence_label == "high":
        return "medium"
    if confidence_label == "medium":
        return "low"
    return "low"


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
