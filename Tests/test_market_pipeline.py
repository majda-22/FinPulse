from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.market_price
import app.db.models.pipeline_event

from app.db.models.company import Company
from app.db.models.market_price import MarketPrice
from app.db.models.pipeline_event import PipelineEvent
from ingestion.market_client import MarketClient
from ingestion.market_repo import upsert_market_prices
from pipelines.run_market_pipeline import run_market_pipeline


def _make_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_market_client_parses_yahoo_chart_payload():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1713398400, 1713484800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1.1, 1.2],
                                "high": [1.3, 1.4],
                                "low": [1.0, 1.1],
                                "close": [1.25, 1.35],
                                "volume": [1000, 2000],
                            }
                        ],
                        "adjclose": [{"adjclose": [1.24, 1.34]}],
                    },
                }
            ],
            "error": None,
        }
    }

    rows = MarketClient._parse_chart_response(
        payload,
        symbol="NKLA",
        provider="yahoo_chart",
    )

    assert len(rows) == 2
    assert rows[0]["ticker"] == "NKLA"
    assert rows[0]["trading_date"] == date(2024, 4, 18)
    assert rows[0]["adjusted_close"] == 1.24
    assert rows[1]["volume"] == 2000


def test_market_client_raises_on_empty_history_payload():
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "validRanges": ["1d", "5d"],
                        "firstTradeDate": None,
                        "regularMarketPrice": 0.183,
                    },
                    "indicators": {"quote": [{}], "adjclose": [{}]},
                }
            ],
            "error": None,
        }
    }

    with pytest.raises(RuntimeError, match="No historical market data returned"):
        MarketClient._parse_chart_response(
            payload,
            symbol="NKLA",
            provider="yahoo_chart",
        )


def test_upsert_market_prices_is_rerun_safe():
    session = _make_session()
    company = Company(cik="0001731289", ticker="NKLA", name="Nikola Corp")
    session.add(company)
    session.flush()

    first = upsert_market_prices(
        session,
        company_id=company.id,
        ticker="NKLA",
        rows=[
            {
                "trading_date": date(2024, 4, 18),
                "open": 1.10,
                "high": 1.30,
                "low": 1.00,
                "close": 1.25,
                "adjusted_close": 1.24,
                "volume": 1000,
                "provider": "yahoo_chart",
                "retrieved_at": datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
            }
        ],
    )
    second = upsert_market_prices(
        session,
        company_id=company.id,
        ticker="NKLA",
        rows=[
            {
                "trading_date": date(2024, 4, 18),
                "open": 1.11,
                "high": 1.31,
                "low": 1.01,
                "close": 1.26,
                "adjusted_close": 1.25,
                "volume": 1200,
                "provider": "yahoo_chart",
                "retrieved_at": datetime(2026, 4, 18, 12, 5, tzinfo=timezone.utc),
            }
        ],
    )

    rows = session.query(MarketPrice).filter_by(company_id=company.id).all()

    assert first["inserted"] == 1
    assert second["updated"] == 1
    assert len(rows) == 1
    assert rows[0].close == Decimal("1.260000")
    assert rows[0].volume == 1200

    session.close()


def test_run_market_pipeline_supports_cik_with_symbol_override():
    session = _make_session()
    company = Company(cik="0001731289", ticker="0001731289", name="Nikola Corp")
    session.add(company)
    session.flush()

    class AsyncMarketClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def fetch_daily_history(self, *, symbol, start=None, end=None, provider="yahoo_chart"):
            assert symbol == "NKLA"
            return [
                {
                    "ticker": symbol,
                    "trading_date": date(2024, 4, 18),
                    "open": 1.10,
                    "high": 1.30,
                    "low": 1.00,
                    "close": 1.25,
                    "adjusted_close": 1.24,
                    "volume": 1000,
                    "provider": provider,
                }
            ]

    with patch(
        "pipelines.run_market_pipeline.MarketClient",
        return_value=AsyncMarketClientStub(),
    ):
        summary = asyncio.run(
            run_market_pipeline(
                cik="0001731289",
                symbol="NKLA",
                start=date(2024, 4, 1),
                end=date(2024, 4, 30),
                db=session,
            )
        )

    rows = session.query(MarketPrice).filter_by(company_id=company.id).all()
    events = session.query(PipelineEvent).filter_by(
        company_id=company.id,
        event_type="market_prices_ingested",
    ).all()

    assert summary["symbol"] == "NKLA"
    assert summary["inserted"] == 1
    assert len(rows) == 1
    assert rows[0].ticker == "NKLA"
    assert len(events) == 1

    session.close()
