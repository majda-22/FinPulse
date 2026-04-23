"""
run_backfill_company.py

Full company backfill runner. This pipeline orchestrates SEC filing ingestion
and processing, Form 4 parsing, news collection, market prices, macro series,
and an optional signal run for one company.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.session import check_connection, get_db
from ingestion.company_repo import log_event
from pipelines.filing_pipeline import run_filing_pipeline
from pipelines.form4_pipeline import run_form4_pipeline
from pipelines.run_macro_pipeline import run_macro_pipeline
from pipelines.run_market_pipeline import run_market_pipeline
from pipelines.run_news_pipeline import run_news_pipeline

logger = logging.getLogger("pipelines.run_backfill_company")


async def run_backfill_company(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    ten_k_max: int = 3,
    ten_q_max: int = 4,
    form4_max: int = 20,
    form4_parse_limit: int = 20,
    news_limit: int = 50,
    symbol: str | None = None,
    filing_start: date | None = None,
    filing_end: date | None = None,
    market_start: date | None = None,
    market_end: date | None = None,
    macro_start: date | None = None,
    macro_end: date | None = None,
    macro_series: list[str] | None = None,
    run_signals: bool = True,
) -> dict[str, Any]:
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    normalized_ticker = ticker.upper().strip() if ticker else None
    normalized_cik = str(cik).strip().zfill(10) if cik else None
    source_kwargs = _make_source_kwargs(
        ticker=normalized_ticker,
        cik=normalized_cik,
    )

    t0 = time.monotonic()
    summary: dict[str, Any] = {
        "ticker": normalized_ticker,
        "cik": normalized_cik,
        "run_signals": run_signals,
        "sources": {},
    }

    try:
        ten_k_summary = await run_filing_pipeline(
            **source_kwargs,
            form_type="10-K",
            max_filings=ten_k_max,
            start=filing_start,
            end=filing_end,
            skip_signals=not run_signals,
        )
        summary["sources"]["10-K"] = ten_k_summary

        resolved_kwargs = _make_source_kwargs(
            ticker=_coalesce_real_ticker(
                normalized_ticker,
                ten_k_summary.get("ticker"),
            ),
            cik=ten_k_summary.get("cik") or normalized_cik,
        )

        ten_q_summary = await run_filing_pipeline(
            **resolved_kwargs,
            form_type="10-Q",
            max_filings=ten_q_max,
            start=filing_start,
            end=filing_end,
            skip_signals=not run_signals,
        )
        summary["sources"]["10-Q"] = ten_q_summary

        form4_summary = await run_form4_pipeline(
            **resolved_kwargs,
            max_filings=form4_max,
            parse_limit=form4_parse_limit,
        )
        summary["sources"]["form4"] = form4_summary

        news_summary = await run_news_pipeline(
            **resolved_kwargs,
            limit=news_limit,
        )
        summary["sources"]["news"] = news_summary

        market_summary = await run_market_pipeline(
            **resolved_kwargs,
            symbol=symbol,
            start=market_start,
            end=market_end,
        )
        summary["sources"]["market"] = market_summary

        macro_summary = await run_macro_pipeline(
            series_ids=macro_series,
            start=macro_start,
            end=macro_end,
        )
        summary["sources"]["macro"] = macro_summary

        duration_ms = int((time.monotonic() - t0) * 1000)
        summary["duration_ms"] = duration_ms
        summary["ticker"] = news_summary.get("ticker") or market_summary.get("ticker") or ten_q_summary.get("ticker") or ten_k_summary.get("ticker") or normalized_ticker
        summary["cik"] = news_summary.get("cik") or market_summary.get("cik") or ten_q_summary.get("cik") or ten_k_summary.get("cik") or normalized_cik

        _log_backfill_event(
            ticker=summary["ticker"],
            cik=summary["cik"],
            event_type="company_backfilled",
            duration_ms=duration_ms,
            detail={
                "step": "run_backfill_company",
                "run_signals": run_signals,
                "ten_k_selected": ten_k_summary["selected"],
                "ten_k_processed": ten_k_summary["processed"],
                "ten_q_selected": ten_q_summary["selected"],
                "ten_q_processed": ten_q_summary["processed"],
                "form4_processed": form4_summary["parse"]["processed"],
                "news_stored": news_summary["stored"],
                "market_stored": market_summary["stored"],
                "macro_stored": macro_summary["stored"],
            },
        )
        return summary
    except Exception as exc:
        _log_backfill_event(
            ticker=summary.get("ticker"),
            cik=summary.get("cik"),
            event_type="failed",
            duration_ms=int((time.monotonic() - t0) * 1000),
            detail={
                "step": "run_backfill_company",
                "run_signals": run_signals,
                "completed_sources": list(summary["sources"].keys()),
                "error": str(exc),
            },
        )
        raise


def _coalesce_real_ticker(
    current_ticker: str | None,
    discovered_ticker: str | None,
) -> str | None:
    if current_ticker:
        return current_ticker
    if discovered_ticker and not discovered_ticker.isdigit():
        return discovered_ticker.upper().strip()
    return None


def _make_source_kwargs(
    *,
    ticker: str | None,
    cik: str | None,
) -> dict[str, str]:
    if ticker:
        return {"ticker": ticker, "cik": None}
    if cik:
        return {"ticker": None, "cik": cik}
    raise ValueError("Provide exactly one of ticker or cik")


def _resolve_company(
    db: Session,
    *,
    ticker: str | None,
    cik: str | None,
) -> Company | None:
    if ticker is not None:
        return db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if cik is not None:
        return db.scalar(select(Company).where(Company.cik == str(cik).strip().zfill(10)))
    return None


def _log_backfill_event(
    *,
    ticker: str | None,
    cik: str | None,
    event_type: str,
    duration_ms: int | None,
    detail: dict[str, Any],
) -> None:
    try:
        with get_db() as db:
            company = _resolve_company(db, ticker=ticker, cik=cik)
            log_event(
                db,
                event_type=event_type,
                layer="orchestration",
                company_id=company.id if company is not None else None,
                duration_ms=duration_ms,
                detail={
                    "ticker": company.ticker if company is not None else ticker,
                    "cik": company.cik if company is not None else cik,
                    **detail,
                },
            )
    except Exception:
        logger.exception("Failed to persist backfill event")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full company backfill pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticker", help="Ticker symbol, e.g. AAPL")
    source.add_argument("--cik", help="SEC CIK, e.g. 0001731289")
    parser.add_argument("--ten-k-max", type=int, default=3, help="Max 10-K filings to ingest/process")
    parser.add_argument("--ten-q-max", type=int, default=4, help="Max 10-Q filings to ingest/process")
    parser.add_argument("--form4-max", type=int, default=20, help="Max Form 4 filings to ingest")
    parser.add_argument("--form4-parse-limit", type=int, default=20, help="Max Form 4 filings to parse")
    parser.add_argument("--news-limit", type=int, default=50, help="Max news items to fetch")
    parser.add_argument("--symbol", help="Market symbol override, useful when company.ticker is not tradable")
    parser.add_argument("--filing-start", help="SEC filing start date YYYY-MM-DD")
    parser.add_argument("--filing-end", help="SEC filing end date YYYY-MM-DD")
    parser.add_argument("--market-start", help="Market data start date YYYY-MM-DD")
    parser.add_argument("--market-end", help="Market data end date YYYY-MM-DD")
    parser.add_argument("--macro-start", help="Macro data start date YYYY-MM-DD")
    parser.add_argument("--macro-end", help="Macro data end date YYYY-MM-DD")
    parser.add_argument("--macro-series", nargs="+", help="Optional list of FRED series ids")
    parser.add_argument("--skip-signals", action="store_true", help="Stop the filing pipelines after embeddings/XBRL")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not check_connection():
        raise SystemExit("Cannot connect to PostgreSQL. Check your .env / Docker setup.")

    filing_start = date.fromisoformat(args.filing_start) if args.filing_start else None
    filing_end = date.fromisoformat(args.filing_end) if args.filing_end else None
    market_start = date.fromisoformat(args.market_start) if args.market_start else None
    market_end = date.fromisoformat(args.market_end) if args.market_end else None
    macro_start = date.fromisoformat(args.macro_start) if args.macro_start else None
    macro_end = date.fromisoformat(args.macro_end) if args.macro_end else None

    result = asyncio.run(
        run_backfill_company(
            ticker=args.ticker,
            cik=args.cik,
            ten_k_max=args.ten_k_max,
            ten_q_max=args.ten_q_max,
            form4_max=args.form4_max,
            form4_parse_limit=args.form4_parse_limit,
            news_limit=args.news_limit,
            symbol=args.symbol,
            filing_start=filing_start,
            filing_end=filing_end,
            market_start=market_start,
            market_end=market_end,
            macro_start=macro_start,
            macro_end=macro_end,
            macro_series=args.macro_series,
            run_signals=not args.skip_signals,
        )
    )

    print("\nCompany Backfill")
    print(f"  Ticker:        {result['ticker']}")
    print(f"  CIK:           {result['cik']}")
    print(f"  Duration (ms): {result['duration_ms']}")
    print(f"  Sources:       {', '.join(result['sources'].keys())}")


if __name__ == "__main__":
    main()
