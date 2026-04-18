from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.news_item
import app.db.models.pipeline_event
import app.db.models.signal_score

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.news_item import NewsItem
from app.db.models.signal_score import SignalScore
from signals.sentiment_signals import compute_and_store_sentiment_signals, compute_sentiment_signals


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_compute_sentiment_signals_builds_recent_tone_and_volume_spike(db_session):
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db_session.add(company)
    db_session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number="0000320193-26-000001",
        form_type="10-K",
        filed_at=date(2026, 1, 31),
        period_of_report=date(2025, 12, 31),
        raw_s3_key="aapl/2026-10k.txt",
    )
    db_session.add(filing)
    db_session.flush()

    anchor_dt = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
    for days_ago, score in (
        (50, 0.2),
        (40, 0.1),
        (20, -0.4),
        (6, -0.7),
        (4, -0.8),
        (2, -0.6),
        (1, -0.9),
    ):
        published_at = anchor_dt - timedelta(days=days_ago)
        db_session.add(
            NewsItem(
                company_id=company.id,
                ticker="AAPL",
                source_name="rss",
                publisher="Example",
                headline=f"headline-{days_ago}",
                summary="summary",
                url=f"https://example.com/{days_ago}",
                published_at=published_at,
                dedupe_hash=f"hash-{days_ago}",
                sentiment_label="negative" if score < 0 else "positive",
                raw_json={"sentiment_score": score},
            )
        )

    db_session.flush()

    signals = compute_sentiment_signals(db_session, filing_id=filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert set(by_name) == {
        "news_sentiment_signal",
        "news_volume_spike",
        "sentiment_signal",
    }
    assert by_name["news_sentiment_signal"]["signal_value"] > 0.5
    assert by_name["news_volume_spike"]["signal_value"] >= 0.0
    assert by_name["sentiment_signal"]["signal_value"] > 0.35


def test_compute_and_store_sentiment_signals_upserts_rows(db_session):
    company = Company(cik="0000789019", ticker="MSFT", name="Microsoft Corp.")
    db_session.add(company)
    db_session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number="0000789019-26-000001",
        form_type="10-Q",
        filed_at=date(2026, 2, 1),
        period_of_report=date(2025, 12, 31),
        raw_s3_key="msft/2026-10q.txt",
    )
    db_session.add(filing)
    db_session.flush()

    db_session.add(
        NewsItem(
            company_id=company.id,
            ticker="MSFT",
            source_name="rss",
            publisher="Example",
            headline="headline",
            summary="summary",
            url="https://example.com/msft",
            published_at=datetime(2026, 1, 31, 9, 0, tzinfo=timezone.utc),
            dedupe_hash="hash",
            sentiment_label="negative",
            raw_json={"sentiment_score": -0.6},
        )
    )
    db_session.flush()

    compute_and_store_sentiment_signals(filing.id, db=db_session)

    rows = db_session.query(SignalScore).filter_by(filing_id=filing.id).all()
    assert {row.signal_name for row in rows} >= {
        "news_sentiment_signal",
        "news_volume_spike",
        "sentiment_signal",
    }
