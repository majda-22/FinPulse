"""
run_news_pipeline.py

End-to-end pipeline for company news. This pipeline resolves a company,
fetches RSS articles, normalizes them, stores them in news_items, and logs a
pipeline event with the ingest summary.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.session import check_connection, get_db
from ingestion.company_repo import log_event, upsert_company
from ingestion.edgar_client import EdgarClient
from ingestion.news_client import NewsClient
from ingestion.news_repo import upsert_news_items
from processing.news_normalizer import normalize_news_items
from processing.news_sentiment import enrich_news_items_with_sentiment

logger = logging.getLogger("pipelines.run_news_pipeline")


async def run_news_pipeline(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    limit: int = 50,
    db: Session | None = None,
) -> dict[str, Any]:
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    normalized_ticker = ticker.upper().strip() if ticker else None
    normalized_cik = str(cik).strip().zfill(10) if cik else None

    if db is None:
        try:
            with get_db() as session:
                return await run_news_pipeline(
                    ticker=normalized_ticker,
                    cik=normalized_cik,
                    limit=limit,
                    db=session,
                )
        except Exception as exc:
            _log_failed_in_new_session(
                ticker=normalized_ticker,
                cik=normalized_cik,
                limit=limit,
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
        t0 = time.monotonic()

        async with NewsClient() as client:
            raw_items = await client.fetch_company_news(
                ticker=company.ticker,
                company_name=company.name,
                limit=limit,
            )
        normalized_items = normalize_news_items(raw_items)
        scored_items = enrich_news_items_with_sentiment(normalized_items)
        write_summary = upsert_news_items(
            db,
            company_id=company.id,
            ticker=company.ticker,
            items=scored_items,
        )
        sentiment_scored = sum(
            1
            for item in scored_items
            if isinstance(item.get("raw_json"), dict) and item["raw_json"].get("sentiment_score") is not None
        )

        duration_ms = int((time.monotonic() - t0) * 1000)
        log_event(
            db,
            event_type="news_ingested",
            layer="polling",
            company_id=company.id,
            duration_ms=duration_ms,
            detail={
                "step": "run_news_pipeline",
                "ticker": company.ticker,
                "cik": company.cik,
                "limit": limit,
                "fetched": len(raw_items),
                "normalized": len(normalized_items),
                "sentiment_scored": sentiment_scored,
                "inserted": write_summary["inserted"],
                "updated": write_summary["updated"],
                "deduped_in_batch": write_summary["deduped_in_batch"],
            },
        )

        return {
            "company_id": company.id,
            "ticker": company.ticker,
            "cik": company.cik,
            "requested_limit": limit,
            "fetched": len(raw_items),
            "normalized": len(normalized_items),
            "sentiment_scored": sentiment_scored,
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
                limit=limit,
                error=str(exc),
            )
        raise


def _resolve_company(
    db: Session,
    *,
    ticker: str | None,
    cik: str | None,
) -> Company:
    company: Company | None = None

    if ticker is not None:
        company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    elif cik is not None:
        company = db.scalar(select(Company).where(Company.cik == str(cik).strip().zfill(10)))

    if company is None:
        identifier = ticker or cik or "unknown"
        raise RuntimeError(f"Company {identifier!r} not found in database")

    return company


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
            "step": "news_company_upsert",
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
    limit: int,
    error: str,
) -> None:
    log_event(
        db,
        event_type="failed",
        layer="polling",
        company_id=company_id,
        detail={
            "step": "run_news_pipeline",
            "ticker": ticker,
            "cik": cik,
            "limit": limit,
            "error": error,
        },
    )


def _log_failed_in_new_session(
    *,
    ticker: str | None,
    cik: str | None,
    limit: int,
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
                limit=limit,
                error=error,
            )
    except Exception:
        logger.exception("Failed to persist news pipeline failure state")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the company news pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticker", help="Ticker symbol, e.g. AAPL")
    source.add_argument("--cik", help="SEC CIK, e.g. 0001731289")
    parser.add_argument("--limit", type=int, default=50, help="Max RSS articles to fetch")
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

    result = asyncio.run(
        run_news_pipeline(
            ticker=args.ticker,
            cik=args.cik,
            limit=args.limit,
        )
    )

    print("\nNews")
    print(f"  Ticker:            {result['ticker']}")
    print(f"  Fetched:           {result['fetched']}")
    print(f"  Normalized:        {result['normalized']}")
    print(f"  Inserted:          {result['inserted']}")
    print(f"  Updated:           {result['updated']}")
    print(f"  Deduped in batch:  {result['deduped_in_batch']}")
    print(f"  Stored:            {result['stored']}")


if __name__ == "__main__":
    main()
