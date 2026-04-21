from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.nci_score

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.nci_score import NciScore
from signals.validation_report import (
    _aggregate_yearly,
    _build_raw_records,
    _build_signal_flags,
    _classify_signal_behavior,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_classify_signal_behavior_flags_flat_series():
    verdict, recommendation = _classify_signal_behavior([0.20, 0.21, 0.23])

    assert verdict == "flat"
    assert "disable" in recommendation.lower()


def test_classify_signal_behavior_flags_missing_series():
    verdict, recommendation = _classify_signal_behavior([])

    assert verdict == "missing"
    assert "disable" in recommendation.lower()


def test_build_signal_flags_uses_yearly_aggregates(db_session):
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db_session.add(company)
    db_session.flush()

    filings = [
        Filing(
            company_id=company.id,
            accession_number=f"0000320193-25-00000{idx}",
            form_type="10-K",
            filed_at=date(year, 1, 31),
            period_of_report=date(year - 1, 9, 30),
            fiscal_year=year - 1,
            raw_s3_key=f"aapl-{year}",
            is_signal_scored=True,
        )
        for idx, year in enumerate((2024, 2025, 2026), start=1)
    ]
    db_session.add_all(filings)
    db_session.flush()

    scores = [
        NciScore(
            company_id=company.id,
            filing_id=filing.id,
            event_type="annual_anchor",
            fiscal_year=filing.fiscal_year,
            nci_global=0.2,
            computed_at=datetime(2026, 4, 20, 12, idx, tzinfo=timezone.utc),
            signal_text=signal_text,
            signal_fundamental=0.4,
            signal_balance=0.3,
            signal_growth=0.2,
            signal_earnings=0.1,
            signal_anomaly=0.2,
            signal_insider=0.0,
            signal_market=None,
            signal_sentiment=None,
        )
        for idx, (filing, signal_text) in enumerate(zip(filings, (0.20, 0.22, 0.21)), start=1)
    ]
    db_session.add_all(scores)
    db_session.commit()

    rows = db_session.execute(
        select(
            Company.ticker,
            Filing.id.label("filing_id"),
            Filing.filed_at,
            NciScore.fiscal_year,
            NciScore.fiscal_quarter,
            NciScore.event_type,
            NciScore.confidence,
            NciScore.coverage_ratio,
            NciScore.signal_text,
            NciScore.signal_fundamental,
            NciScore.signal_balance,
            NciScore.signal_growth,
            NciScore.signal_earnings,
            NciScore.signal_anomaly,
            NciScore.signal_insider,
            NciScore.signal_market,
            NciScore.signal_sentiment,
        )
        .join(Company, Company.id == NciScore.company_id)
        .outerjoin(Filing, Filing.id == NciScore.filing_id)
        .where(Company.ticker == "AAPL")
        .order_by(Filing.filed_at.asc(), NciScore.computed_at.asc(), NciScore.id.asc())
    ).all()
    raw_records = _build_raw_records(rows)
    yearly = _aggregate_yearly(raw_records)
    flags = _build_signal_flags(yearly)

    text_flag = next(flag for flag in flags if flag.signal_key == "text_drift")
    market_flag = next(flag for flag in flags if flag.signal_key == "market")

    assert text_flag.verdict == "flat"
    assert market_flag.verdict == "missing"
