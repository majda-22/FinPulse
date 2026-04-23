from __future__ import annotations

import asyncio
from unittest.mock import patch

from pipelines.run_backfill_company import run_backfill_company


def test_run_backfill_company_orchestrates_sources_in_order():
    calls: list[tuple[str, dict]] = []

    async def fake_run_filing_pipeline(**kwargs):
        calls.append((f"filing:{kwargs['form_type']}", kwargs))
        return {
            "ticker": "AAPL",
            "cik": "0000320193",
            "selected": kwargs["max_filings"],
            "processed": kwargs["max_filings"],
        }

    async def fake_run_form4_pipeline(**kwargs):
        calls.append(("form4", kwargs))
        return {"parse": {"processed": 7}}

    async def fake_run_news_pipeline(**kwargs):
        calls.append(("news", kwargs))
        return {"ticker": "AAPL", "cik": "0000320193", "stored": 50}

    async def fake_run_market_pipeline(**kwargs):
        calls.append(("market", kwargs))
        return {"ticker": "AAPL", "cik": "0000320193", "stored": 252}

    async def fake_run_macro_pipeline(**kwargs):
        calls.append(("macro", kwargs))
        return {"stored": 1234}

    logged_events: list[dict] = []

    def fake_log_backfill_event(**kwargs):
        logged_events.append(kwargs)

    with patch(
        "pipelines.run_backfill_company.run_filing_pipeline",
        side_effect=fake_run_filing_pipeline,
    ), patch(
        "pipelines.run_backfill_company.run_form4_pipeline",
        side_effect=fake_run_form4_pipeline,
    ), patch(
        "pipelines.run_backfill_company.run_news_pipeline",
        side_effect=fake_run_news_pipeline,
    ), patch(
        "pipelines.run_backfill_company.run_market_pipeline",
        side_effect=fake_run_market_pipeline,
    ), patch(
        "pipelines.run_backfill_company.run_macro_pipeline",
        side_effect=fake_run_macro_pipeline,
    ), patch(
        "pipelines.run_backfill_company._log_backfill_event",
        side_effect=fake_log_backfill_event,
    ):
        summary = asyncio.run(
            run_backfill_company(
                ticker="AAPL",
                ten_k_max=2,
                ten_q_max=3,
                form4_max=7,
                news_limit=11,
                run_signals=False,
            )
        )

    assert [name for name, _ in calls] == [
        "filing:10-K",
        "filing:10-Q",
        "form4",
        "news",
        "market",
        "macro",
    ]
    assert calls[0][1]["skip_signals"] is True
    assert calls[1][1]["skip_signals"] is True
    assert calls[2][1]["max_filings"] == 7
    assert calls[3][1]["limit"] == 11
    assert summary["ticker"] == "AAPL"
    assert summary["sources"]["market"]["stored"] == 252
    assert logged_events[0]["event_type"] == "company_backfilled"
