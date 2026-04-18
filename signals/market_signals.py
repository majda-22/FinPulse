from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.market_price import MarketPrice
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.catalog import get_signal_definition
from signals.common import clip01, coverage_ratio, weighted_average
from signals.history import ANNUAL_FORMS, QUARTERLY_FORMS
from signals.numeric_features import build_period_metrics, load_canonical_xbrl_facts
from signals.policies import MARKET_SIGNAL_WEIGHTS
from signals.signal_repo import mark_signal_stage, upsert_signal_scores

MARKET_SIGNAL_MODEL_VERSION = "market_signals_v1"
SUPPORTED_FILING_FORMS = tuple(sorted(ANNUAL_FORMS | QUARTERLY_FORMS))


@dataclass(slots=True)
class ComputedMarketSignal:
    filing_id: int
    company_id: int
    signal_name: str
    signal_value: float | None
    detail: dict[str, Any]
    model_version: str = MARKET_SIGNAL_MODEL_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_market_signals(
    db: Session,
    *,
    filing_id: int,
    model_version: str = MARKET_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    prices = _load_price_series(db, company_id=filing.company_id, anchor_date=filing.filed_at)
    if not prices:
        signal_names = (
            "price_momentum_risk",
            "volatility_spike",
            "market_fundamental_divergence",
            "market_signal",
        )
        return [
            _not_available_market_signal(
                filing=filing,
                signal_name=signal_name,
                model_version=model_version,
                availability_reason="missing_market_prices",
                extra_detail={"anchor_date": filing.filed_at.isoformat()},
            ).to_dict()
            for signal_name in signal_names
        ]

    latest_price = prices[-1]
    price_lookup = {row["trading_date"]: row["price"] for row in prices}
    daily_returns = _daily_returns(prices)

    momentum_value, momentum_components = _price_momentum_risk(
        anchor_date=latest_price["trading_date"],
        anchor_price=latest_price["price"],
        price_lookup=price_lookup,
    )
    volatility_value, volatility_components = _volatility_spike(daily_returns)
    divergence_value, divergence_components = _market_fundamental_divergence(
        db,
        filing=filing,
        anchor_date=filing.filed_at,
        latest_price=float(latest_price["price"]),
    )
    market_signal_value, market_components = weighted_average(
        {
            "price_momentum_risk": momentum_value,
            "volatility_spike": volatility_value,
            "market_fundamental_divergence": divergence_value,
        },
        MARKET_SIGNAL_WEIGHTS,
    )

    payloads = [
        ("price_momentum_risk", momentum_value, momentum_components),
        ("volatility_spike", volatility_value, volatility_components),
        ("market_fundamental_divergence", divergence_value, divergence_components),
        ("market_signal", market_signal_value, market_components),
    ]

    signals: list[ComputedMarketSignal] = []
    for signal_name, signal_value, component_scores in payloads:
        definition = get_signal_definition(signal_name)
        if signal_value is None:
            signals.append(
                _not_available_market_signal(
                    filing=filing,
                    signal_name=signal_name,
                    model_version=model_version,
                    availability_reason="insufficient_market_history",
                    extra_detail={
                        "description": definition.description if definition else "",
                        "anchor_date": latest_price["trading_date"].isoformat(),
                        "component_scores": component_scores,
                    },
                )
            )
            continue

        signals.append(
            ComputedMarketSignal(
                filing_id=filing.id,
                company_id=filing.company_id,
                signal_name=signal_name,
                signal_value=signal_value,
                model_version=model_version,
                detail={
                    "description": definition.description if definition else "",
                    "anchor_date": latest_price["trading_date"].isoformat(),
                    "price_observation_count": len(prices),
                    "component_scores": component_scores,
                    "coverage_ratio": coverage_ratio(
                        component_scores,
                        expected_count=max(len(component_scores), 1),
                    ),
                    "confidence": _market_confidence(
                        price_count=len(prices),
                        component_scores=component_scores,
                    ),
                    "signal_category": "market",
                    "signal_role": "base" if signal_name != "market_signal" else "composite_layer",
                    "model_version": model_version,
                },
            )
        )

    return [signal.to_dict() for signal in signals]


def compute_and_store_market_signals(
    filing_id: int,
    *,
    db: Session | None = None,
    model_version: str = MARKET_SIGNAL_MODEL_VERSION,
) -> list[dict[str, Any]]:
    if db is None:
        with get_db() as session:
            return compute_and_store_market_signals(
                filing_id,
                db=session,
                model_version=model_version,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    signals = compute_market_signals(
        db,
        filing_id=filing_id,
        model_version=model_version,
    )
    upsert_signal_scores(db, signals)

    mark_signal_stage(filing, processing_status="market_signal_scored")
    filing.last_error_message = None

    log_event(
        db,
        event_type="signal_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "market_signals",
            "model_version": model_version,
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"] for signal in signals if signal["signal_value"] is None
            ],
        },
    )
    return signals


def _price_momentum_risk(
    *,
    anchor_date: date,
    anchor_price: float,
    price_lookup: dict[date, float],
) -> tuple[float | None, dict[str, float]]:
    if anchor_price <= 0:
        return None, {}

    windows = (
        (30, 0.40, "return_1m"),
        (90, 0.30, "return_3m"),
        (180, 0.20, "return_6m"),
        (365, 0.10, "return_12m"),
    )
    components: dict[str, float] = {}
    weighted_negative = 0.0
    available = 0

    for days_back, weight, label in windows:
        comparison_price = _price_on_or_before(
            price_lookup,
            anchor_date - timedelta(days=days_back),
        )
        if comparison_price is None or comparison_price <= 0:
            continue
        rate_of_return = (anchor_price - comparison_price) / comparison_price
        components[label] = rate_of_return
        available += 1
        if rate_of_return < 0:
            weighted_negative += abs(rate_of_return) * weight

    if available == 0:
        return None, {}

    return clip01(weighted_negative / 0.40), components


def _volatility_spike(daily_returns: list[float]) -> tuple[float | None, dict[str, float]]:
    if len(daily_returns) < 30:
        return None, {}

    recent = np.asarray(daily_returns[-30:], dtype=float)
    baseline_source = np.asarray(daily_returns[-180:], dtype=float) if len(daily_returns) >= 180 else np.asarray(daily_returns, dtype=float)
    if baseline_source.size < 30:
        return None, {}

    rolling_vol_30d = float(np.std(recent, ddof=0) * np.sqrt(252.0))
    rolling_vol_180d = float(np.std(baseline_source, ddof=0) * np.sqrt(252.0))
    if rolling_vol_180d == 0.0:
        return None, {}

    vol_ratio = rolling_vol_30d / rolling_vol_180d
    return clip01((vol_ratio - 1.0) / 1.5), {
        "rolling_vol_30d": rolling_vol_30d,
        "rolling_vol_180d": rolling_vol_180d,
        "vol_ratio": vol_ratio,
    }


def _market_fundamental_divergence(
    db: Session,
    *,
    filing: Filing,
    anchor_date: date,
    latest_price: float,
) -> tuple[float | None, dict[str, float]]:
    company = db.get(Company, filing.company_id)
    if company is None or not company.sector:
        return None, {}

    current_pe = _company_pe_ratio(
        db,
        company_id=filing.company_id,
        anchor_date=anchor_date,
        latest_price=latest_price,
    )
    if current_pe is None or current_pe <= 0:
        return None, {}

    peer_ids = db.scalars(
        select(Company.id)
        .where(
            Company.sector == company.sector,
            Company.id != company.id,
        )
        .order_by(Company.id.asc())
    ).all()

    peer_pes = [
        peer_pe
        for peer_id in peer_ids
        if (peer_pe := _company_pe_ratio(db, company_id=peer_id, anchor_date=anchor_date)) is not None and peer_pe > 0
    ]
    if len(peer_pes) < 3:
        return None, {"current_pe": current_pe}

    sector_median_pe = float(median(peer_pes))
    if sector_median_pe <= 0:
        return None, {"current_pe": current_pe}

    overvaluation_ratio = current_pe / sector_median_pe
    return clip01((overvaluation_ratio - 1.0) / 2.0), {
        "current_pe": current_pe,
        "sector_median_pe": sector_median_pe,
        "overvaluation_ratio": overvaluation_ratio,
        "peer_count": float(len(peer_pes)),
    }


def _company_pe_ratio(
    db: Session,
    *,
    company_id: int,
    anchor_date: date,
    latest_price: float | None = None,
) -> float | None:
    latest_filing = db.scalar(
        select(Filing)
        .where(
            Filing.company_id == company_id,
            Filing.form_type.in_(SUPPORTED_FILING_FORMS),
            Filing.filed_at <= anchor_date,
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )
    if latest_filing is None:
        return None

    if latest_price is None:
        price_row = db.scalar(
            select(MarketPrice)
            .where(
                MarketPrice.company_id == company_id,
                MarketPrice.trading_date <= anchor_date,
            )
            .order_by(MarketPrice.trading_date.desc(), MarketPrice.id.desc())
            .limit(1)
        )
        if price_row is None:
            return None
        latest_price = _row_price(price_row)
    if latest_price is None or latest_price <= 0:
        return None

    raw_facts = load_canonical_xbrl_facts(db, filings=[latest_filing]).get(latest_filing.id, {})
    metrics = build_period_metrics(raw_facts, form_type=latest_filing.form_type)
    net_income = metrics.get("net_income")
    shares_outstanding = metrics.get("shares_outstanding")
    if net_income is None or shares_outstanding is None or net_income <= 0 or shares_outstanding <= 0:
        return None

    market_cap = latest_price * shares_outstanding
    return market_cap / net_income


def _load_price_series(
    db: Session,
    *,
    company_id: int,
    anchor_date: date,
) -> list[dict[str, float | date]]:
    rows = db.scalars(
        select(MarketPrice)
        .where(
            MarketPrice.company_id == company_id,
            MarketPrice.trading_date <= anchor_date,
        )
        .order_by(MarketPrice.trading_date.asc(), MarketPrice.id.asc())
    ).all()

    return [
        {
            "trading_date": row.trading_date,
            "price": _row_price(row),
        }
        for row in rows
        if _row_price(row) is not None
    ]


def _row_price(row: MarketPrice) -> float | None:
    if row.adjusted_close is not None:
        return float(row.adjusted_close)
    if row.close is not None:
        return float(row.close)
    return None


def _price_on_or_before(price_lookup: dict[date, float], target_date: date) -> float | None:
    eligible = [day for day in price_lookup if day <= target_date]
    if not eligible:
        return None
    return price_lookup[max(eligible)]


def _daily_returns(prices: list[dict[str, float | date]]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        previous_price = float(previous["price"])
        current_price = float(current["price"])
        if previous_price <= 0:
            continue
        returns.append((current_price - previous_price) / previous_price)
    return returns


def _market_confidence(*, price_count: int, component_scores: dict[str, float]) -> float:
    history_ratio = clip01(price_count / 252.0)
    component_ratio = coverage_ratio(component_scores, expected_count=max(len(component_scores), 1))
    return clip01((0.70 * history_ratio) + (0.30 * component_ratio))


def _not_available_market_signal(
    *,
    filing: Filing,
    signal_name: str,
    model_version: str,
    availability_reason: str,
    extra_detail: dict[str, Any],
) -> ComputedMarketSignal:
    return ComputedMarketSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name=signal_name,
        signal_value=None,
        model_version=model_version,
        detail={
            "availability_reason": availability_reason,
            "coverage_ratio": 0.0,
            "confidence": 0.0,
            "signal_category": "market",
            "signal_role": "base" if signal_name != "market_signal" else "composite_layer",
            "model_version": model_version,
            **extra_detail,
        },
    )
