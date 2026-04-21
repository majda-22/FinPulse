from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.news_item
import app.db.models.pipeline_event

from app.db.models.company import Company
from app.db.models.news_item import NewsItem
from app.db.models.pipeline_event import PipelineEvent
from pipelines.news_sentiment_backfill import backfill_news_sentiment
from ingestion.edgar_client import CompanyMeta
from ingestion.news_repo import upsert_news_items
from pipelines.run_news_pipeline import run_news_pipeline
from processing.news_normalizer import normalize_news_item


def _make_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_normalize_news_item_cleans_fields_and_builds_hash():
    raw_item = {
        "ticker": "aapl",
        "headline": " Apple launches something new - Reuters ",
        "summary": "<p> Apple launches   something new. </p>",
        "url": "https://news.google.com/rss/articles/CBMiY2h0dHBzOi8vZXhhbXBsZS5jb20vbmV3cz91dG1fc291cmNlPXJzc9IBAA?oc=5",
        "publisher": "Reuters",
        "published_at": "Fri, 18 Apr 2026 10:00:00 GMT",
        "source_name": "google_news_rss",
        "raw_json": {"id": "abc123"},
    }

    normalized = normalize_news_item(raw_item)

    assert normalized is not None
    assert normalized["ticker"] == "AAPL"
    assert normalized["headline"] == "Apple launches something new - Reuters"
    assert normalized["summary"] == "Apple launches something new."
    assert normalized["published_at"] == datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc)
    assert len(normalized["dedupe_hash"]) == 64


def test_upsert_news_items_is_rerun_safe_per_company():
    session = _make_session()
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    session.add(company)
    session.flush()

    item = {
        "source_name": "google_news_rss",
        "publisher": "Reuters",
        "headline": "Apple launches something new",
        "summary": "First summary",
        "url": "https://example.com/apple-news",
        "published_at": datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
        "retrieved_at": datetime(2026, 4, 18, 10, 5, tzinfo=timezone.utc),
        "dedupe_hash": "abc123",
        "sentiment_label": None,
        "raw_json": {"version": 1},
    }

    first = upsert_news_items(
        session,
        company_id=company.id,
        ticker=company.ticker,
        items=[item],
    )
    second = upsert_news_items(
        session,
        company_id=company.id,
        ticker=company.ticker,
        items=[{**item, "summary": "Updated summary", "raw_json": {"version": 2}}],
    )

    rows = session.query(NewsItem).filter_by(company_id=company.id).all()

    assert first["inserted"] == 1
    assert second["updated"] == 1
    assert len(rows) == 1
    assert rows[0].summary == "Updated summary"
    assert rows[0].raw_json == {"version": 2}

    session.close()


def test_run_news_pipeline_fetches_normalizes_and_logs_event():
    session = _make_session()
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    session.add(company)
    session.flush()

    raw_items = [
        {
            "ticker": "AAPL",
            "headline": "Apple expands services business",
            "summary": "<p>Services growth continues.</p>",
            "url": "https://example.com/apple-services",
            "publisher": "Reuters",
            "published_at": "Fri, 18 Apr 2026 11:00:00 GMT",
            "source_name": "google_news_rss",
            "raw_json": {"id": "news-1"},
        },
        {
            "ticker": "AAPL",
            "headline": "Apple expands services business",
            "summary": "<p>Services growth continues.</p>",
            "url": "https://example.com/apple-services",
            "publisher": "Reuters",
            "published_at": "Fri, 18 Apr 2026 11:00:00 GMT",
            "source_name": "google_news_rss",
            "raw_json": {"id": "news-1-duplicate"},
        },
    ]

    class AsyncNewsClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def fetch_company_news(self, *, ticker, company_name=None, limit=50):
            return raw_items[:limit]

    def _fake_sentiment_enricher(items):
        enriched = []
        for item in items:
            payload = dict(item)
            payload["sentiment_label"] = "positive"
            payload["raw_json"] = {
                **(payload.get("raw_json") or {}),
                "sentiment_score": 0.42,
            }
            enriched.append(payload)
        return enriched

    with patch(
        "pipelines.run_news_pipeline.NewsClient",
        return_value=AsyncNewsClientStub(),
    ), patch(
        "pipelines.run_news_pipeline.enrich_news_items_with_sentiment",
        side_effect=_fake_sentiment_enricher,
    ):
        summary = asyncio.run(
            run_news_pipeline(
                ticker="AAPL",
                limit=50,
                db=session,
            )
        )

    rows = session.query(NewsItem).filter_by(company_id=company.id).all()
    events = session.query(PipelineEvent).filter_by(
        company_id=company.id,
        event_type="news_ingested",
    ).all()

    assert summary["fetched"] == 2
    assert summary["normalized"] == 2
    assert summary["deduped_in_batch"] == 1
    assert summary["inserted"] == 1
    assert summary["sentiment_scored"] == 2
    assert len(rows) == 1
    assert rows[0].sentiment_label == "positive"
    assert rows[0].raw_json["sentiment_score"] == 0.42
    assert len(events) == 1

    session.close()


def test_run_news_pipeline_bootstraps_missing_company():
    session = _make_session()

    raw_items = [
        {
            "ticker": "NKLA",
            "headline": "Nikola signs a new partnership",
            "summary": "<p>Partnership details announced.</p>",
            "url": "https://example.com/nikola-partnership",
            "publisher": "Reuters",
            "published_at": "Fri, 18 Apr 2026 12:00:00 GMT",
            "source_name": "google_news_rss",
            "raw_json": {"id": "nkla-1"},
        }
    ]

    class AsyncNewsClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def fetch_company_news(self, *, ticker, company_name=None, limit=50):
            return raw_items[:limit]

    class AsyncEdgarClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_company_meta(self, ticker):
            return CompanyMeta(
                cik="0001731289",
                ticker=ticker,
                name="Nikola Corporation",
                sic_code="3711",
                sic_description="Motor Vehicles",
                exchange="NASDAQ",
            )

    with patch(
        "pipelines.run_news_pipeline.NewsClient",
        return_value=AsyncNewsClientStub(),
    ), patch(
        "pipelines.run_news_pipeline.EdgarClient",
        return_value=AsyncEdgarClientStub(),
    ):
        summary = asyncio.run(
            run_news_pipeline(
                ticker="NKLA",
                limit=50,
                db=session,
            )
        )

    company = session.query(Company).filter_by(ticker="NKLA").one()
    rows = session.query(NewsItem).filter_by(company_id=company.id).all()

    assert summary["ticker"] == "NKLA"
    assert summary["inserted"] == 1
    assert company.cik == "0001731289"
    assert len(rows) == 1

    session.close()


def test_backfill_news_sentiment_updates_existing_rows():
    session = _make_session()
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    session.add(company)
    session.flush()

    row = NewsItem(
        company_id=company.id,
        ticker="AAPL",
        source_name="google_news_rss",
        publisher="Reuters",
        headline="Apple launches a new product",
        summary="Investors react positively.",
        url="https://example.com/apple-product",
        published_at=datetime(2026, 4, 18, 11, 0, tzinfo=timezone.utc),
        dedupe_hash="aapl-news-1",
        sentiment_label=None,
        raw_json={"source": "fixture"},
    )
    session.add(row)
    session.flush()

    def _fake_sentiment_enricher(items):
        enriched = []
        for item in items:
            payload = dict(item)
            payload["sentiment_label"] = "positive"
            payload["raw_json"] = {
                **(payload.get("raw_json") or {}),
                "sentiment_score": 0.33,
            }
            enriched.append(payload)
        return enriched

    with patch(
        "pipelines.news_sentiment_backfill.enrich_news_items_with_sentiment",
        side_effect=_fake_sentiment_enricher,
    ):
        summary = backfill_news_sentiment(ticker="AAPL", db=session)

    session.refresh(row)
    assert summary["updated"] == 1
    assert row.sentiment_label == "positive"
    assert row.raw_json["sentiment_score"] == 0.33

    session.close()
