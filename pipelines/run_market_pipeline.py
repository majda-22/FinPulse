"""
run_market_pipeline.py

End-to-end pipeline for daily market prices. This pipeline resolves a company,
fetches daily OHLCV history for a date range, stores it in market_prices, and
logs a pipeline event with the ingest summary.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.session import check_connection, get_db
from ingestion.company_repo import log_event, upsert_company
from ingestion.edgar_client import EdgarClient
from ingestion.market_client import DEFAULT_MARKET_PROVIDER, MarketClient
from ingestion.market_repo import upsert_market_prices

logger = logging.getLogger("pipelines.run_market_pipeline")


async def run_market_pipeline(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    symbol: str | None = None,
    start: date | None = None,
    end: date | None = None,
    provider: str = DEFAULT_MARKET_PROVIDER,
    db: Session | None = None,
) -> dict[str, Any]:
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    normalized_ticker = ticker.upper().strip() if ticker else None
    normalized_cik = str(cik).strip().zfill(10) if cik else None

    if db is None:
        try:
            with get_db() as session:
                return await run_market_pipeline(
                    ticker=normalized_ticker,
                    cik=normalized_cik,
                    symbol=symbol,
                    start=start,
                    end=end,
                    provider=provider,
                    db=session,
                )
        except Exception as exc:
            _log_failed_in_new_session(
                ticker=normalized_ticker,
                cik=normalized_cik,
                limit_context={
                    "symbol": symbol,
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                    "provider": provider,
                },
                error=str(exc),
            )
            raise

    company: Company | None = None
    try:
        company = await _resolve_or_bootstrap_company(
            db,
            ticker=normalized_ticker,
            cik=normalized_cik,
        )
        market_symbol = _resolve_market_symbol(
            ticker=normalized_ticker,
            company=company,
            symbol=symbol,
        )

        end_date = end or date.today()
        start_date = start or (end_date - timedelta(days=365))
        if start_date > end_date:
            raise ValueError("start date must be on or before end date")

        t0 = time.monotonic()

        async with MarketClient() as client:
            rows = await client.fetch_daily_history(
                symbol=market_symbol,
                start=start_date,
                end=end_date,
                provider=provider,
            )
        if not rows:
            raise RuntimeError(
                "No market price rows returned for "
                f"{market_symbol!r} from {provider} "
                f"between {start_date.isoformat()} and {end_date.isoformat()}"
            )

        write_summary = upsert_market_prices(
            db,
            company_id=company.id,
            ticker=market_symbol,
            rows=rows,
        )

        duration_ms = int((time.monotonic() - t0) * 1000)
        log_event(
            db,
            event_type="market_prices_ingested",
            layer="polling",
            company_id=company.id,
            duration_ms=duration_ms,
            detail={
                "step": "run_market_pipeline",
                "ticker": company.ticker,
                "cik": company.cik,
                "symbol": market_symbol,
                "provider": provider,
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "fetched": len(rows),
                "inserted": write_summary["inserted"],
                "updated": write_summary["updated"],
                "deduped_in_batch": write_summary["deduped_in_batch"],
            },
        )

        return {
            "company_id": company.id,
            "ticker": company.ticker,
            "cik": company.cik,
            "symbol": market_symbol,
            "provider": provider,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "fetched": len(rows),
            **write_summary,
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        if company is not None:
            _log_failed(
                db,
                company_id=company.id,
                ticker=company.ticker,
                cik=company.cik,
                detail={
                    "symbol": symbol,
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                    "provider": provider,
                },
                error=str(exc),
            )
        raise


def _resolve_market_symbol(
    *,
    ticker: str | None,
    company: Company,
    symbol: str | None,
) -> str:
    if symbol:
        return symbol.upper().strip()
    if ticker:
        return ticker.upper().strip()

    company_ticker = company.ticker.strip().upper()
    if company_ticker and not company_ticker.isdigit():
        return company_ticker

    raise RuntimeError(
        "Unable to determine market symbol from the company record. "
        "Pass --symbol explicitly."
    )


async def _resolve_or_bootstrap_company(
    db: Session,
    *,
    ticker: str | None,
    cik: str | None,
) -> Company:
    company = _get_company(db, ticker=ticker, cik=cik)
    if company is not None:
        return company

    async with EdgarClient() as client:
        if ticker is not None:
            meta = await client.get_company_meta(ticker)
        elif cik is not None:
            meta = await client.get_company_meta_by_cik(cik)
        else:
            raise ValueError("Provide exactly one of ticker or cik")

    company = upsert_company(db, meta)
    log_event(
        db,
        event_type="ingested",
        layer="polling",
        company_id=company.id,
        detail={
            "step": "market_company_upsert",
            "ticker": company.ticker,
            "cik": company.cik,
        },
    )
    return company


def _get_company(
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


def _log_failed(
    db: Session,
    *,
    company_id: int | None,
    ticker: str | None,
    cik: str | None,
    detail: dict[str, Any],
    error: str,
) -> None:
    log_event(
        db,
        event_type="failed",
        layer="polling",
        company_id=company_id,
        detail={
            "step": "run_market_pipeline",
            "ticker": ticker,
            "cik": cik,
            "error": error,
            **detail,
        },
    )


def _log_failed_in_new_session(
    *,
    ticker: str | None,
    cik: str | None,
    limit_context: dict[str, Any],
    error: str,
) -> None:
    try:
        with get_db() as db:
            company = _get_company(db, ticker=ticker, cik=cik)
            _log_failed(
                db,
                company_id=company.id if company is not None else None,
                ticker=company.ticker if company is not None else ticker,
                cik=company.cik if company is not None else cik,
                detail=limit_context,
                error=error,
            )
    except Exception:
        logger.exception("Failed to persist market pipeline failure state")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the market price pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticker", help="Ticker symbol, e.g. AAPL")
    source.add_argument("--cik", help="SEC CIK, e.g. 0001731289")
    parser.add_argument("--symbol", help="Market symbol override, useful when company.ticker is not tradable")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default: 1 year ago)")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--provider",
        default=DEFAULT_MARKET_PROVIDER,
        help=f"Price source label (default: {DEFAULT_MARKET_PROVIDER})",
    )
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

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    result = asyncio.run(
        run_market_pipeline(
            ticker=args.ticker,
            cik=args.cik,
            symbol=args.symbol,
            start=start,
            end=end,
            provider=args.provider,
        )
    )

    print("\nMarket Prices")
    print(f"  Ticker:            {result['ticker']}")
    print(f"  Symbol:            {result['symbol']}")
    print(f"  Provider:          {result['provider']}")
    print(f"  Start:             {result['start']}")
    print(f"  End:               {result['end']}")
    print(f"  Fetched:           {result['fetched']}")
    print(f"  Inserted:          {result['inserted']}")
    print(f"  Updated:           {result['updated']}")
    print(f"  Deduped in batch:  {result['deduped_in_batch']}")
    print(f"  Stored:            {result['stored']}")


if __name__ == "__main__":
    main()
