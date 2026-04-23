from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.market_price
import app.db.models.pipeline_event
import app.db.models.signal_score
import app.db.models.xbrl_fact

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.market_price import MarketPrice
from app.db.models.signal_score import SignalScore
from app.db.models.xbrl_fact import XbrlFact
from signals.market_signals import compute_and_store_market_signals, compute_market_signals


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_company_with_filing(db_session, *, ticker: str, cik: str, sector: str, filing_date: date) -> Filing:
    company = Company(cik=cik, ticker=ticker, name=f"{ticker} Corp", sector=sector)
    db_session.add(company)
    db_session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number=f"{cik}-{filing_date.year}-000001",
        form_type="10-K",
        filed_at=filing_date,
        period_of_report=filing_date,
        raw_s3_key=f"{ticker}/{filing_date.year}/10-k.txt",
        is_xbrl_parsed=True,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _seed_xbrl(db_session, *, filing: Filing, company: Company, net_income: float, shares_outstanding: float):
    facts = [
        ("NetIncomeLoss", net_income),
        ("CommonStockSharesOutstanding", shares_outstanding),
        ("Revenues", net_income * 8),
        ("Assets", net_income * 20),
        ("GrossProfit", net_income * 4),
        ("OperatingIncomeLoss", net_income * 2),
        ("StockholdersEquity", net_income * 10),
        ("LongTermDebt", net_income * 3),
        ("CashAndCashEquivalentsAtCarryingValue", net_income * 2),
        ("NetCashProvidedByUsedInOperatingActivities", net_income * 1.5),
    ]
    for concept, value in facts:
        db_session.add(
            XbrlFact(
                company_id=company.id,
                filing_id=filing.id,
                taxonomy="us-gaap",
                concept=concept,
                value=value,
                unit="USD" if concept != "CommonStockSharesOutstanding" else "shares",
                period_type="duration" if concept not in {"Assets", "StockholdersEquity", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue", "CommonStockSharesOutstanding"} else "instant",
                period_start=filing.period_of_report - timedelta(days=365) if concept not in {"Assets", "StockholdersEquity", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue", "CommonStockSharesOutstanding"} else None,
                period_end=filing.period_of_report,
                form_type=filing.form_type,
            )
        )


def test_compute_market_signals_builds_market_layer_scores(db_session):
    anchor_filing = _seed_company_with_filing(
        db_session,
        ticker="TSLA",
        cik="0001318605",
        sector="auto",
        filing_date=date(2026, 1, 31),
    )
    anchor_company = db_session.get(Company, anchor_filing.company_id)
    _seed_xbrl(db_session, filing=anchor_filing, company=anchor_company, net_income=100.0, shares_outstanding=10.0)

    peer_specs = [
        ("F", "0000000001", 20.0),
        ("GM", "0000000002", 18.0),
        ("RIVN", "0000000003", 22.0),
    ]
    for ticker, cik, price in peer_specs:
        peer_filing = _seed_company_with_filing(
            db_session,
            ticker=ticker,
            cik=cik,
            sector="auto",
            filing_date=date(2025, 12, 31),
        )
        peer_company = db_session.get(Company, peer_filing.company_id)
        _seed_xbrl(db_session, filing=peer_filing, company=peer_company, net_income=100.0, shares_outstanding=10.0)
        db_session.add(
            MarketPrice(
                company_id=peer_company.id,
                ticker=ticker,
                trading_date=anchor_filing.filed_at,
                close=price,
                adjusted_close=price,
                volume=1000000,
                provider="yfinance",
            )
        )

    start = anchor_filing.filed_at - timedelta(days=220)
    for offset in range(0, 221):
        trading_day = start + timedelta(days=offset)
        if trading_day.weekday() >= 5:
            continue
        price = 250.0 - (offset * 0.6)
        db_session.add(
            MarketPrice(
                company_id=anchor_company.id,
                ticker="TSLA",
                trading_date=trading_day,
                close=price,
                adjusted_close=price,
                volume=1000000 + (offset * 1000),
                provider="yfinance",
            )
        )

    db_session.flush()

    signals = compute_market_signals(db_session, filing_id=anchor_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert set(by_name) == {
        "price_momentum_risk",
        "volatility_spike",
        "market_fundamental_divergence",
        "market_signal",
    }
    assert by_name["price_momentum_risk"]["signal_value"] > 0.5
    assert by_name["market_fundamental_divergence"]["signal_value"] > 0.4
    assert by_name["market_signal"]["signal_value"] > 0.4


def test_compute_and_store_market_signals_upserts_rows(db_session):
    filing = _seed_company_with_filing(
        db_session,
        ticker="AAPL",
        cik="0000320193",
        sector="tech",
        filing_date=date(2026, 1, 31),
    )
    company = db_session.get(Company, filing.company_id)
    _seed_xbrl(db_session, filing=filing, company=company, net_income=120.0, shares_outstanding=8.0)
    db_session.add(
        MarketPrice(
            company_id=company.id,
            ticker="AAPL",
            trading_date=filing.filed_at,
            close=100.0,
            adjusted_close=100.0,
            volume=1000,
            provider="yfinance",
        )
    )
    db_session.flush()

    compute_and_store_market_signals(filing.id, db=db_session)

    rows = db_session.query(SignalScore).filter_by(filing_id=filing.id).all()
    assert {row.signal_name for row in rows} >= {
        "price_momentum_risk",
        "volatility_spike",
        "market_fundamental_divergence",
        "market_signal",
    }
