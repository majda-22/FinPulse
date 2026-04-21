from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.news_item import NewsItem
from app.db.session import get_db
from ingestion.company_repo import log_event
from processing.news_sentiment import enrich_news_items_with_sentiment

logger = logging.getLogger("pipelines.news_sentiment_backfill")


def backfill_news_sentiment(
    *,
    ticker: str | None = None,
    limit: int | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    normalized_ticker = ticker.upper().strip() if ticker else None

    if db is None:
        with get_db() as session:
            return backfill_news_sentiment(
                ticker=normalized_ticker,
                limit=limit,
                db=session,
            )

    query = select(NewsItem).order_by(NewsItem.published_at.asc(), NewsItem.id.asc())
    if normalized_ticker is not None:
        query = query.join(Company, Company.id == NewsItem.company_id).where(Company.ticker == normalized_ticker)

    rows = db.scalars(query).all()
    rows_to_score = [row for row in rows if _sentiment_missing(row)]
    if limit is not None:
        rows_to_score = rows_to_score[:limit]

    if not rows_to_score:
        return {
            "ticker": normalized_ticker,
            "selected": len(rows),
            "updated": 0,
            "remaining_missing": 0,
        }

    payloads = [
        {
            "headline": row.headline,
            "summary": row.summary,
            "sentiment_label": row.sentiment_label,
            "raw_json": row.raw_json,
        }
        for row in rows_to_score
    ]
    scored_payloads = enrich_news_items_with_sentiment(payloads)

    updated = 0
    for row, payload in zip(rows_to_score, scored_payloads):
        raw_json = payload.get("raw_json")
        if not isinstance(raw_json, dict) or raw_json.get("sentiment_score") is None:
            continue
        row.raw_json = raw_json
        row.sentiment_label = payload.get("sentiment_label")
        updated += 1

    if rows_to_score:
        company_id = rows_to_score[0].company_id if normalized_ticker and updated > 0 else None
        log_event(
            db,
            event_type="news_sentiment_backfilled",
            layer="processing",
            company_id=company_id,
            detail={
                "step": "news_sentiment_backfill",
                "ticker": normalized_ticker,
                "selected": len(rows_to_score),
                "updated": updated,
            },
        )

    remaining_missing = sum(1 for row in rows if _sentiment_missing(row))
    return {
        "ticker": normalized_ticker,
        "selected": len(rows_to_score),
        "updated": updated,
        "remaining_missing": remaining_missing,
    }


def _sentiment_missing(row: NewsItem) -> bool:
    if not isinstance(row.raw_json, dict):
        return True
    return row.raw_json.get("sentiment_score") is None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill FinBERT sentiment into existing news_items rows")
    parser.add_argument("--ticker", help="Optional ticker filter, e.g. AAPL")
    parser.add_argument("--limit", type=int, help="Optional cap on rows to process")
    return parser.parse_args()


def main(*, ticker: str | None = None, limit: int | None = None) -> dict[str, Any]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    result = backfill_news_sentiment(ticker=ticker, limit=limit)
    print(result)
    return result


if __name__ == "__main__":
    args = _parse_args()
    main(ticker=args.ticker, limit=args.limit)
