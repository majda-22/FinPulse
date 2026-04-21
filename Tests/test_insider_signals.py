from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.insider_transaction
import app.db.models.pipeline_event
import app.db.models.signal_score

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.pipeline_event import PipelineEvent
from app.db.models.signal_score import SignalScore
from signals.behavior_features import _role_name
from ingestion.insider_repo import upsert_insider_transactions
from signals.insider_features import compute_insider_features_for_filing
from signals.insider_signals import compute_and_store_insider_signals, compute_insider_signals
from signals.signal_repo import upsert_signal_scores


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
    row = Company(cik="0001318605", ticker="TSLA", name="Tesla, Inc.")
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def anchor_filing(db_session, company):
    filing = Filing(
        company_id=company.id,
        accession_number="0001318605-26-000001",
        form_type="10-K",
        filed_at=date(2026, 1, 31),
        period_of_report=date(2025, 12, 31),
        raw_s3_key="tsla/2026-10k",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _transaction(
    *,
    company: Company,
    accession_number: str,
    insider_name: str,
    insider_cik: str,
    transaction_date: date,
    transaction_code: str,
    transaction_type_normalized: str,
    shares: float,
    price_per_share: float,
    shares_owned_after: float,
    is_director: bool = False,
    is_officer: bool = False,
    officer_title: str | None = None,
) -> dict:
    return {
        "filing_id": None,
        "company_id": company.id,
        "transaction_uid": (
            f"{accession_number}|{insider_name}|{transaction_date.isoformat()}|"
            f"{transaction_code}|{shares}|{price_per_share}"
        ),
        "accession_number": accession_number,
        "cik": company.cik,
        "ticker": company.ticker,
        "issuer_name": company.name,
        "security_title": "Common Stock",
        "insider_name": insider_name,
        "insider_cik": insider_cik,
        "is_director": is_director,
        "is_officer": is_officer,
        "is_ten_percent_owner": False,
        "is_other": False,
        "officer_title": officer_title,
        "transaction_date": transaction_date,
        "transaction_code": transaction_code,
        "transaction_type_normalized": transaction_type_normalized,
        "shares": shares,
        "price_per_share": price_per_share,
        "transaction_value": shares * price_per_share,
        "shares_owned_after": shares_owned_after,
        "ownership_nature": "direct",
        "acquired_disposed_code": "D" if transaction_code == "S" else "A",
        "is_derivative": False,
        "form_type": "4",
        "filed_at": transaction_date,
        "source_url": None,
        "raw_detail": {"seed": True},
    }


@pytest.fixture
def insider_history(db_session, company, anchor_filing):
    rows = [
        _transaction(
            company=company,
            accession_number="hist-ceo-1",
            insider_name="Elon Musk",
            insider_cik="0001494730",
            transaction_date=date(2025, 3, 1),
            transaction_code="S",
            transaction_type_normalized="open_market_sell",
            shares=100.0,
            price_per_share=150.0,
            shares_owned_after=99900.0,
            is_officer=True,
            officer_title="Chief Executive Officer",
        ),
        _transaction(
            company=company,
            accession_number="hist-cfo-1",
            insider_name="Vaibhav Taneja",
            insider_cik="0001771340",
            transaction_date=date(2025, 4, 1),
            transaction_code="S",
            transaction_type_normalized="open_market_sell",
            shares=120.0,
            price_per_share=148.0,
            shares_owned_after=79880.0,
            is_officer=True,
            officer_title="Chief Financial Officer",
        ),
        _transaction(
            company=company,
            accession_number="hist-dir-1",
            insider_name="Kimbal Musk",
            insider_cik="0001494731",
            transaction_date=date(2025, 5, 1),
            transaction_code="S",
            transaction_type_normalized="open_market_sell",
            shares=90.0,
            price_per_share=149.0,
            shares_owned_after=10910.0,
            is_director=True,
        ),
        _transaction(
            company=company,
            accession_number="sell-ceo-1",
            insider_name="Elon Musk",
            insider_cik="0001494730",
            transaction_date=date(2026, 1, 10),
            transaction_code="S",
            transaction_type_normalized="open_market_sell",
            shares=1200.0,
            price_per_share=200.0,
            shares_owned_after=98800.0,
            is_officer=True,
            officer_title="Chief Executive Officer",
        ),
        _transaction(
            company=company,
            accession_number="sell-cfo-1",
            insider_name="Vaibhav Taneja",
            insider_cik="0001771340",
            transaction_date=date(2026, 1, 12),
            transaction_code="S",
            transaction_type_normalized="open_market_sell",
            shares=1100.0,
            price_per_share=198.0,
            shares_owned_after=78780.0,
            is_officer=True,
            officer_title="Chief Financial Officer",
        ),
        _transaction(
            company=company,
            accession_number="sell-dir-1",
            insider_name="Kimbal Musk",
            insider_cik="0001494731",
            transaction_date=date(2026, 1, 18),
            transaction_code="S",
            transaction_type_normalized="open_market_sell",
            shares=1050.0,
            price_per_share=197.0,
            shares_owned_after=9860.0,
            is_director=True,
        ),
        _transaction(
            company=company,
            accession_number="buy-vp-1",
            insider_name="Vice President Small",
            insider_cik="0001888888",
            transaction_date=date(2026, 1, 20),
            transaction_code="P",
            transaction_type_normalized="open_market_buy",
            shares=1500.0,
            price_per_share=196.0,
            shares_owned_after=6500.0,
            is_officer=True,
            officer_title="Vice President",
        ),
    ]

    upsert_insider_transactions(db_session, rows)
    upsert_signal_scores(
        db_session,
        [
            {
                "filing_id": anchor_filing.id,
                "company_id": company.id,
                "signal_name": "text_sentiment",
                "signal_value": 0.8,
                "detail": {"seed": True},
                "model_version": "test",
            }
        ],
    )
    return rows


def test_compute_insider_features_for_filing_builds_opportunistic_window_metrics(
    db_session,
    anchor_filing,
    insider_history,
):
    snapshot = compute_insider_features_for_filing(db_session, filing_id=anchor_filing.id)
    features = snapshot["features"]

    assert snapshot["transaction_row_count"] == 7
    assert features["historical_transaction_count"] == 3
    assert features["opportunistic_sell_count"] == 3
    assert features["opportunistic_buy_count"] == 0
    assert features["unique_sellers_in_window"] == 3
    assert features["opportunistic_sell_value"] > 600000.0


def test_compute_insider_signals_returns_v2_behavior_signal_families(
    db_session,
    anchor_filing,
    insider_history,
):
    signals = compute_insider_signals(db_session, filing_id=anchor_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert set(by_name) == {"ita", "insider_concentration", "insider_signal"}
    assert by_name["ita"]["signal_value"] > 0.8
    assert by_name["insider_concentration"]["signal_value"] == pytest.approx(0.75)
    assert by_name["insider_signal"]["signal_value"] > 0.75


def test_compute_and_store_insider_signals_upserts_and_marks_stage(
    db_session,
    anchor_filing,
    insider_history,
):
    first = compute_and_store_insider_signals(anchor_filing.id, db=db_session)
    second = compute_and_store_insider_signals(anchor_filing.id, db=db_session)

    rows = db_session.query(SignalScore).filter_by(filing_id=anchor_filing.id).all()
    events = db_session.query(PipelineEvent).filter_by(
        filing_id=anchor_filing.id,
        event_type="signal_scored",
    ).all()

    stored_names = {row.signal_name for row in rows}

    assert len(first) == 3
    assert len(second) == 3
    assert {"text_sentiment", "ita", "insider_concentration", "insider_signal"} <= stored_names
    assert anchor_filing.is_insider_signal_scored is True
    assert anchor_filing.is_signal_scored is False
    assert anchor_filing.processing_status == "insider_signal_scored"
    assert len(events) == 2


def test_upsert_insider_transactions_matches_existing_business_key_when_uid_changes(
    db_session,
    company,
):
    base = _transaction(
        company=company,
        accession_number="0001104659-26-038682",
        insider_name="Wilson-Thompson Kathleen",
        insider_cik="0001331680",
        transaction_date=date(2026, 3, 30),
        transaction_code="S",
        transaction_type_normalized="open_market_sell",
        shares=80.0,
        price_per_share=352.833,
        shares_owned_after=57669.0,
        is_director=True,
    )
    base["transaction_uid"] = "uid-original"

    inserted, updated = upsert_insider_transactions(db_session, [base])
    assert inserted == 1
    assert updated == 0

    rerun = dict(base)
    rerun["transaction_uid"] = "uid-rerun"
    rerun["raw_detail"] = {"seed": False}

    inserted, updated = upsert_insider_transactions(db_session, [rerun])

    rows = db_session.query(app.db.models.insider_transaction.InsiderTransaction).all()

    assert inserted == 0
    assert updated == 1
    assert len(rows) == 1
    assert rows[0].transaction_uid == "uid-rerun"


def test_compute_insider_signals_without_transactions_returns_not_available(
    db_session,
    company,
):
    filing = Filing(
        company_id=company.id,
        accession_number="0001318605-26-000001",
        form_type="10-K",
        filed_at=date(2026, 1, 31),
        period_of_report=date(2025, 12, 31),
        raw_s3_key="tsla/2026-10k",
    )
    db_session.add(filing)
    db_session.flush()

    signals = compute_insider_signals(db_session, filing_id=filing.id)

    assert len(signals) == 3
    assert all(signal["signal_value"] is None for signal in signals)
    assert all(signal["detail"]["availability_reason"] == "no_insider_transactions" for signal in signals)


def test_role_name_does_not_misclassify_senior_vice_president_titles():
    svp = type(
        "Txn",
        (),
        {
            "officer_title": "Senior Vice President",
            "is_director": False,
        },
    )()
    cfo = type(
        "Txn",
        (),
        {
            "officer_title": "Senior Vice President, CFO",
            "is_director": False,
        },
    )()

    assert _role_name(svp) == "Other Officer"
    assert _role_name(cfo) == "CFO"
