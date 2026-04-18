from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from statistics import mean
from typing import Any, Iterable

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.xbrl_fact import XbrlFact
from signals.common import safe_divide
from signals.history import ANNUAL_FORMS, QUARTERLY_FORMS, load_comparable_filing_history


CANONICAL_FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenueFromContractWithCustomerExcludingAssessedTaxNetOfReturns",
        "SalesRevenueNet",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss", "IncomeFromOperations", "OperatingIncome"),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "assets": ("Assets",),
    "liabilities": ("Liabilities", "LiabilitiesAndStockholdersEquity"),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "long_term_debt": (
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "shares_outstanding": (
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "CommonStocksIncludingAdditionalPaidInCapitalSharesOutstanding",
    ),
}

DURATION_FACTS = {
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
}

NUMERIC_FEATURES_VERSION = "numeric_features_v2"


@dataclass(slots=True)
class NumericFeatureSnapshot:
    filing_id: int
    company_id: int
    form_type: str
    period_end: date | None
    comparison_filing_id: int | None
    history_filing_ids: list[int]
    raw_facts: dict[str, float | None]
    current_metrics: dict[str, float | None]
    prior_metrics: dict[str, float | None]
    features: dict[str, float | None]
    feature_version: str = NUMERIC_FEATURES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_numeric_feature_snapshot(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
) -> dict[str, Any]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    history = load_comparable_filing_history(db, filing_id=filing_id, history_limit=history_limit)
    raw_by_filing = load_canonical_xbrl_facts(db, filings=history)
    metrics_by_filing: dict[int, dict[str, float | None]] = {}

    previous_metrics: dict[str, float | None] | None = None
    for history_filing in history:
        raw_facts = raw_by_filing.get(history_filing.id, {})
        metrics = build_period_metrics(raw_facts, form_type=history_filing.form_type)
        metrics["revenue_growth"] = (
            _growth(raw_facts.get("revenue"), previous_metrics.get("revenue") if previous_metrics else None)
            if previous_metrics is not None
            else None
        )
        metrics_by_filing[history_filing.id] = metrics
        previous_metrics = metrics

    current_filing = history[-1]
    prior_filing = history[-2] if len(history) >= 2 else None
    two_back_filing = history[-3] if len(history) >= 3 else None
    current_metrics = metrics_by_filing.get(current_filing.id, {})
    prior_metrics = metrics_by_filing.get(prior_filing.id, {}) if prior_filing is not None else {}
    two_back_metrics = metrics_by_filing.get(two_back_filing.id, {}) if two_back_filing is not None else {}

    zscores, anomaly_distance = _numeric_anomaly_components(
        current_metrics=current_metrics,
        historical_metrics=[metrics_by_filing[row.id] for row in history[:-1]],
    )

    features = {
        "gross_margin_current": current_metrics.get("gross_margin"),
        "gross_margin_prior": prior_metrics.get("gross_margin"),
        "gross_margin_delta": _delta(current_metrics.get("gross_margin"), prior_metrics.get("gross_margin")),
        "operating_margin_current": current_metrics.get("operating_margin"),
        "operating_margin_prior": prior_metrics.get("operating_margin"),
        "operating_margin_delta": _delta(current_metrics.get("operating_margin"), prior_metrics.get("operating_margin")),
        "net_margin_current": current_metrics.get("net_margin"),
        "net_margin_prior": prior_metrics.get("net_margin"),
        "net_margin_delta": _delta(current_metrics.get("net_margin"), prior_metrics.get("net_margin")),
        "revenue_growth_current": current_metrics.get("revenue_growth"),
        "revenue_growth_prior": prior_metrics.get("revenue_growth"),
        "revenue_growth_two_back": two_back_metrics.get("revenue_growth"),
        "debt_to_equity_current": current_metrics.get("debt_to_equity"),
        "debt_to_equity_prior": prior_metrics.get("debt_to_equity"),
        "cash_ratio_current": current_metrics.get("cash_ratio"),
        "cash_ratio_prior": prior_metrics.get("cash_ratio"),
        "cf_quality_current": current_metrics.get("cf_quality"),
        "accruals_ratio_current": current_metrics.get("accruals_ratio"),
        "shares_outstanding_current": current_metrics.get("shares_outstanding"),
        "numeric_anomaly_distance": anomaly_distance,
        **zscores,
    }

    return NumericFeatureSnapshot(
        filing_id=current_filing.id,
        company_id=current_filing.company_id,
        form_type=current_filing.form_type,
        period_end=current_filing.period_of_report,
        comparison_filing_id=prior_filing.id if prior_filing is not None else None,
        history_filing_ids=[row.id for row in history[:-1]],
        raw_facts=raw_by_filing.get(current_filing.id, {}),
        current_metrics=current_metrics,
        prior_metrics=prior_metrics,
        features=features,
    ).to_dict()


def compute_xbrl_features_for_filing(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
) -> dict[str, Any]:
    return compute_numeric_feature_snapshot(db, filing_id=filing_id, history_limit=history_limit)


def load_canonical_xbrl_facts(
    db: Session,
    *,
    filings: Iterable[Filing],
) -> dict[int, dict[str, float | None]]:
    filings = list(filings)
    if not filings:
        return {}

    filing_ids = [filing.id for filing in filings]
    all_concepts = {
        concept
        for aliases in CANONICAL_FACT_ALIASES.values()
        for concept in aliases
    }

    rows = db.scalars(
        select(XbrlFact)
        .where(
            XbrlFact.filing_id.in_(filing_ids),
            XbrlFact.concept.in_(all_concepts),
        )
    ).all()

    rows_by_filing: dict[int, list[XbrlFact]] = {}
    for row in rows:
        if row.filing_id is None:
            continue
        rows_by_filing.setdefault(row.filing_id, []).append(row)

    result: dict[int, dict[str, float | None]] = {}
    for filing in filings:
        filing_rows = rows_by_filing.get(filing.id, [])
        raw_facts: dict[str, float | None] = {}

        for canonical_name, aliases in CANONICAL_FACT_ALIASES.items():
            selected = _select_best_fact(
                filing_rows,
                filing=filing,
                canonical_name=canonical_name,
                aliases=aliases,
            )
            raw_facts[canonical_name] = float(selected.value) if selected is not None and selected.value is not None else None

        result[filing.id] = raw_facts

    return result


def _select_best_fact(
    rows: list[XbrlFact],
    *,
    filing: Filing,
    canonical_name: str,
    aliases: tuple[str, ...],
) -> XbrlFact | None:
    candidates = [row for row in rows if row.concept in aliases and row.value is not None]
    if not candidates:
        return None

    usd_candidates = [row for row in candidates if row.unit == "USD"]
    if usd_candidates:
        candidates = usd_candidates

    alias_rank = {alias: index for index, alias in enumerate(aliases)}
    period_end = filing.period_of_report or filing.filed_at
    target_days = 365 if filing.form_type in ANNUAL_FORMS else 90

    def rank(row: XbrlFact) -> tuple[int, int, int]:
        end_distance = abs((row.period_end - period_end).days) if period_end is not None else 0
        if canonical_name in DURATION_FACTS and row.period_start is not None:
            duration_distance = abs((row.period_end - row.period_start).days - target_days)
        else:
            duration_distance = 0
        return (
            alias_rank.get(row.concept, len(alias_rank)),
            end_distance,
            duration_distance,
        )

    return min(candidates, key=rank)


def build_period_metrics(
    raw_facts: dict[str, float | None],
    *,
    form_type: str,
) -> dict[str, float | None]:
    revenue = _annualize_if_quarterly(raw_facts.get("revenue"), form_type=form_type)
    gross_profit = _annualize_if_quarterly(raw_facts.get("gross_profit"), form_type=form_type)
    operating_income = _annualize_if_quarterly(raw_facts.get("operating_income"), form_type=form_type)
    net_income = _annualize_if_quarterly(raw_facts.get("net_income"), form_type=form_type)
    assets = raw_facts.get("assets")
    equity = raw_facts.get("equity")
    long_term_debt = raw_facts.get("long_term_debt")
    cash = raw_facts.get("cash")
    operating_cash_flow = _annualize_if_quarterly(raw_facts.get("operating_cash_flow"), form_type=form_type)
    shares_outstanding = raw_facts.get("shares_outstanding")

    gross_margin = safe_divide(gross_profit, revenue)
    operating_margin = safe_divide(operating_income, revenue)
    net_margin = safe_divide(net_income, revenue)
    debt_to_equity = safe_divide(long_term_debt, equity)
    cash_ratio = safe_divide(cash, assets)

    cf_quality = None
    if net_income is not None and operating_cash_flow is not None and net_income > 0:
        cf_quality = safe_divide(operating_cash_flow, net_income)

    accruals_ratio = None
    if net_income is not None and operating_cash_flow is not None:
        accruals_ratio = safe_divide(net_income - operating_cash_flow, assets)

    return {
        "revenue": revenue,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "debt_to_equity": debt_to_equity,
        "cash_ratio": cash_ratio,
        "cf_quality": cf_quality,
        "accruals_ratio": accruals_ratio,
        "net_income": net_income,
        "shares_outstanding": shares_outstanding,
    }


def _build_period_metrics(raw_facts: dict[str, float | None]) -> dict[str, float | None]:
    return build_period_metrics(raw_facts, form_type="10-K")


def _numeric_anomaly_components(
    *,
    current_metrics: dict[str, float | None],
    historical_metrics: list[dict[str, float | None]],
) -> tuple[dict[str, float | None], float | None]:
    metric_names = ("gross_margin", "operating_margin", "revenue_growth", "debt_to_equity")
    zscores: dict[str, float | None] = {}
    distances: list[float] = []

    for metric_name in metric_names:
        current_value = current_metrics.get(metric_name)
        series = [
            float(metrics[metric_name])
            for metrics in historical_metrics
            if metrics.get(metric_name) is not None
        ]
        if current_value is None or len(series) < 2:
            zscores[f"{metric_name}_zscore"] = None
            continue

        historical_mean = float(mean(series))
        historical_std = float(np.std(series))
        if historical_std == 0.0:
            zscore = 0.0 if current_value == historical_mean else (3.0 if current_value > historical_mean else -3.0)
        else:
            zscore = float((current_value - historical_mean) / historical_std)
        zscores[f"{metric_name}_zscore"] = zscore
        distances.append(zscore ** 2)

    anomaly_distance = None
    if distances:
        anomaly_distance = float(np.sqrt(sum(distances) / len(distances)))

    return zscores, anomaly_distance


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float((current - previous) / previous)


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return float(current - previous)


def _annualize_if_quarterly(value: float | None, *, form_type: str) -> float | None:
    if value is None:
        return None
    if form_type in QUARTERLY_FORMS:
        return float(value) * 4.0
    return float(value)
