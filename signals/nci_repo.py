from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.nci_score import NciScore


def upsert_nci_score(
    db: Session,
    *,
    company_id: int,
    filing_id: int | None,
    signal_score_id: int | None,
    nci_global: float,
    model_version: str,
    event_type: str,
    fiscal_year: int | None = None,
    fiscal_quarter: int | None = None,
    convergence_tier: str | None = None,
    layers_elevated: int | None = None,
    confidence: str | None = None,
    coverage_ratio: float | None = None,
    signal_text: float | None = None,
    signal_mda: float | None = None,
    signal_pessimism: float | None = None,
    signal_fundamental: float | None = None,
    signal_balance: float | None = None,
    signal_growth: float | None = None,
    signal_earnings: float | None = None,
    signal_anomaly: float | None = None,
    signal_insider: float | None = None,
    signal_market: float | None = None,
    signal_sentiment: float | None = None,
    text_source_filing: int | None = None,
    xbrl_source_filing: int | None = None,
    text_staleness_days: int | None = None,
    data_fresh: bool = True,
    staleness_reason: str | None = None,
    top_anomalous_paragraphs: dict[str, Any] | list[Any] | None = None,
    nci_lower: float | None = None,
    nci_upper: float | None = None,
    computed_at: datetime | None = None,
) -> NciScore:
    existing = None
    if filing_id is not None:
        existing = db.scalar(
            select(NciScore)
            .where(
                NciScore.company_id == company_id,
                NciScore.filing_id == filing_id,
                NciScore.event_type == event_type,
            )
            .order_by(NciScore.created_at.desc(), NciScore.id.desc())
            .limit(1)
        )

    effective_computed_at = computed_at or datetime.now(timezone.utc)

    if existing is None:
        existing = NciScore(
            company_id=company_id,
            filing_id=filing_id,
            signal_score_id=signal_score_id,
            text_source_filing=text_source_filing,
            xbrl_source_filing=xbrl_source_filing,
            event_type=event_type,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            nci_global=nci_global,
            nci_lower=nci_lower,
            nci_upper=nci_upper,
            convergence_tier=convergence_tier,
            layers_elevated=layers_elevated,
            confidence=confidence,
            coverage_ratio=coverage_ratio,
            model_version=model_version,
            data_fresh=data_fresh,
            staleness_reason=staleness_reason,
            top_anomalous_paragraphs=top_anomalous_paragraphs,
            text_staleness_days=text_staleness_days,
            signal_text=signal_text,
            signal_mda=signal_mda,
            signal_pessimism=signal_pessimism,
            signal_fundamental=signal_fundamental,
            signal_balance=signal_balance,
            signal_growth=signal_growth,
            signal_earnings=signal_earnings,
            signal_anomaly=signal_anomaly,
            signal_insider=signal_insider,
            signal_market=signal_market,
            signal_sentiment=signal_sentiment,
            computed_at=effective_computed_at,
        )
        db.add(existing)
    else:
        existing.signal_score_id = signal_score_id
        existing.text_source_filing = text_source_filing
        existing.xbrl_source_filing = xbrl_source_filing
        existing.event_type = event_type
        existing.fiscal_year = fiscal_year
        existing.fiscal_quarter = fiscal_quarter
        existing.nci_global = nci_global
        existing.nci_lower = nci_lower
        existing.nci_upper = nci_upper
        existing.convergence_tier = convergence_tier
        existing.layers_elevated = layers_elevated
        existing.confidence = confidence
        existing.coverage_ratio = coverage_ratio
        existing.model_version = model_version
        existing.data_fresh = data_fresh
        existing.staleness_reason = staleness_reason
        existing.top_anomalous_paragraphs = top_anomalous_paragraphs
        existing.text_staleness_days = text_staleness_days
        existing.signal_text = signal_text
        existing.signal_mda = signal_mda
        existing.signal_pessimism = signal_pessimism
        existing.signal_fundamental = signal_fundamental
        existing.signal_balance = signal_balance
        existing.signal_growth = signal_growth
        existing.signal_earnings = signal_earnings
        existing.signal_anomaly = signal_anomaly
        existing.signal_insider = signal_insider
        existing.signal_market = signal_market
        existing.signal_sentiment = signal_sentiment
        existing.computed_at = effective_computed_at

    db.flush()
    return existing
