from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.pipeline_event
import app.db.models.signal_score
import app.db.models.xbrl_fact

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.pipeline_event import PipelineEvent
from app.db.models.signal_score import SignalScore
from app.db.models.xbrl_fact import XbrlFact
from signals.xbrl_features import compute_xbrl_features_for_filing
from signals.xbrl_signals import compute_and_store_xbrl_signals, compute_xbrl_signals


CANONICAL_TO_CONCEPT = {
    "revenue": "Revenues",
    "gross_profit": "GrossProfit",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "assets": "Assets",
    "liabilities": "Liabilities",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "long_term_debt": "LongTermDebtNoncurrent",
    "equity": "StockholdersEquity",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
}
DURATION_FACTS = {
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
}


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def company(db_session):
    row = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def annual_filings(db_session, company):
    filings = []
    for year in (2021, 2022, 2023, 2024, 2025):
        filing = Filing(
            company_id=company.id,
            accession_number=f"0000320193-{str(year)[2:]}-0000{year - 2020}",
            form_type="10-K",
            filed_at=date(year + 1, 1, 31),
            period_of_report=date(year, 9, 30),
            fiscal_year=year,
            raw_s3_key=f"filing-{year}",
            is_xbrl_parsed=True,
        )
        db_session.add(filing)
        db_session.flush()
        filings.append(filing)
    return filings


@pytest.fixture
def populated_xbrl_history(db_session, company, annual_filings):
    values_by_year = {
        2021: {
            "revenue": 820.0,
            "gross_profit": 380.0,
            "operating_income": 180.0,
            "net_income": 135.0,
            "assets": 1800.0,
            "liabilities": 760.0,
            "cash": 330.0,
            "long_term_debt": 260.0,
            "equity": 1040.0,
            "operating_cash_flow": 195.0,
        },
        2022: {
            "revenue": 900.0,
            "gross_profit": 430.0,
            "operating_income": 210.0,
            "net_income": 160.0,
            "assets": 1900.0,
            "liabilities": 800.0,
            "cash": 360.0,
            "long_term_debt": 280.0,
            "equity": 1100.0,
            "operating_cash_flow": 220.0,
        },
        2023: {
            "revenue": 1000.0,
            "gross_profit": 470.0,
            "operating_income": 240.0,
            "net_income": 190.0,
            "assets": 2000.0,
            "liabilities": 850.0,
            "cash": 380.0,
            "long_term_debt": 300.0,
            "equity": 1150.0,
            "operating_cash_flow": 250.0,
        },
        2024: {
            "revenue": 1200.0,
            "gross_profit": 600.0,
            "operating_income": 320.0,
            "net_income": 250.0,
            "assets": 2200.0,
            "liabilities": 950.0,
            "cash": 450.0,
            "long_term_debt": 320.0,
            "equity": 1250.0,
            "operating_cash_flow": 310.0,
        },
        2025: {
            "revenue": 1180.0,
            "gross_profit": 540.0,
            "operating_income": 240.0,
            "net_income": 170.0,
            "assets": 2350.0,
            "liabilities": 1300.0,
            "cash": 320.0,
            "long_term_debt": 500.0,
            "equity": 1050.0,
            "operating_cash_flow": 190.0,
        },
    }

    for filing in annual_filings:
        year = filing.period_of_report.year
        values = values_by_year[year]
        for canonical_name, concept in CANONICAL_TO_CONCEPT.items():
            period_start = date(year - 1, 10, 1) if canonical_name in DURATION_FACTS else None
            period_type = "duration" if canonical_name in DURATION_FACTS else "instant"

            db_session.add(
                XbrlFact(
                    company_id=company.id,
                    filing_id=filing.id,
                    taxonomy="us-gaap",
                    concept=concept,
                    label=concept,
                    value=values[canonical_name],
                    unit="USD",
                    decimals="-6",
                    period_type=period_type,
                    period_start=period_start,
                    period_end=filing.period_of_report,
                    fiscal_year=year,
                    fiscal_quarter=None,
                    form_type=filing.form_type,
                )
            )

    db_session.flush()
    return annual_filings


def test_compute_xbrl_features_for_filing_builds_expected_numeric_snapshot(
    db_session,
    populated_xbrl_history,
):
    current = populated_xbrl_history[-1]
    previous = populated_xbrl_history[-2]

    snapshot = compute_xbrl_features_for_filing(db_session, filing_id=current.id)
    features = snapshot["features"]

    assert snapshot["comparison_filing_id"] == previous.id
    assert features["gross_margin_current"] == pytest.approx(540.0 / 1180.0)
    assert features["operating_margin_delta"] < 0
    assert features["net_margin_delta"] < 0
    assert features["debt_to_equity_current"] == pytest.approx(500.0 / 1050.0)
    assert features["cash_ratio_current"] == pytest.approx(320.0 / 2350.0)
    assert features["cf_quality_current"] == pytest.approx(190.0 / 170.0)
    assert features["cash_conversion_ratio_current"] == pytest.approx(190.0 / 170.0)
    assert features["accruals_ratio_prior"] == pytest.approx((250.0 - 310.0) / 2200.0)
    assert features["operating_cash_flow_current"] == pytest.approx(190.0)
    assert features["net_income_current"] == pytest.approx(170.0)
    assert features["numeric_anomaly_distance"] is not None
    assert "numeric_anomaly_components" in features
    assert "gross_margin" in features["numeric_anomaly_components"]


def test_compute_xbrl_signals_returns_v2_numeric_signal_families(db_session, populated_xbrl_history):
    current = populated_xbrl_history[-1]

    signals = compute_xbrl_signals(db_session, filing_id=current.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert set(by_name) == {
        "fundamental_deterioration",
        "revenue_growth_deceleration",
        "balance_sheet_stress",
        "earnings_quality",
        "numeric_anomaly",
    }
    assert by_name["fundamental_deterioration"]["signal_value"] == pytest.approx(0.2810381356, rel=1e-6)
    assert by_name["revenue_growth_deceleration"]["signal_value"] == pytest.approx(0.7222222222, rel=1e-6)
    assert by_name["balance_sheet_stress"]["signal_value"] == pytest.approx(0.2821923922, rel=1e-6)
    assert by_name["earnings_quality"]["signal_value"] == pytest.approx(0.0296920241, rel=1e-6)
    assert by_name["earnings_quality"]["detail"]["component_scores"]["accruals_score"] == pytest.approx(0.0)
    assert by_name["earnings_quality"]["detail"]["component_scores"]["cash_conversion_score"] == pytest.approx(0.0)
    assert by_name["earnings_quality"]["detail"]["component_scores"]["consistency_score"] == pytest.approx(0.1484601206, rel=1e-6)
    assert 0.0 <= by_name["numeric_anomaly"]["signal_value"] <= 1.0


def test_numeric_anomaly_requires_four_prior_periods(db_session, populated_xbrl_history):
    current = populated_xbrl_history[3]

    signals = compute_xbrl_signals(db_session, filing_id=current.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert by_name["numeric_anomaly"]["signal_value"] is None
    assert by_name["numeric_anomaly"]["detail"]["availability_reason"] == "insufficient_numeric_history"


def test_compute_and_store_xbrl_signals_upserts_and_marks_filing_scored(
    db_session,
    populated_xbrl_history,
):
    current = populated_xbrl_history[-1]

    first = compute_and_store_xbrl_signals(current.id, db=db_session)
    second = compute_and_store_xbrl_signals(current.id, db=db_session)

    rows = db_session.query(SignalScore).filter_by(filing_id=current.id).all()
    events = db_session.query(PipelineEvent).filter_by(
        filing_id=current.id,
        event_type="signal_scored",
    ).all()

    assert len(first) == 5
    assert len(second) == 5
    assert len(rows) == 5
    assert current.is_numeric_signal_scored is True
    assert current.is_signal_scored is False
    assert current.processing_status == "numeric_signal_scored"
    assert len(events) == 2


def test_compute_xbrl_signals_without_xbrl_facts_returns_not_available(db_session, company):
    filing = Filing(
        company_id=company.id,
        accession_number="0000320193-25-000079",
        form_type="10-K",
        filed_at=date(2026, 1, 31),
        period_of_report=date(2025, 9, 30),
        raw_s3_key="empty",
    )
    db_session.add(filing)
    db_session.flush()

    signals = compute_xbrl_signals(db_session, filing_id=filing.id)

    assert len(signals) == 5
    assert all(signal["signal_value"] is None for signal in signals)
    assert all(signal["detail"]["availability_reason"] == "no_xbrl_facts" for signal in signals)
