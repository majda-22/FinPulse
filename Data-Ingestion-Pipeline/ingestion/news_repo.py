"""
news_repo.py

Database read/write helpers for news_items. Handles per-company deduplication,
rerun-safe upserts, and simple batch summaries for the news pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.news_item import NewsItem


def upsert_news_items(
    db: Session,
    *,
    company_id: int,
    ticker: str,
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    unique_items = _dedupe_batch(items)
    dedupe_hashes = [str(item["dedupe_hash"]) for item in unique_items]

    existing_rows = db.scalars(
        select(NewsItem).where(
            NewsItem.company_id == company_id,
            NewsItem.dedupe_hash.in_(dedupe_hashes),
        )
    ).all() if dedupe_hashes else []
    existing_by_hash = {row.dedupe_hash: row for row in existing_rows}

    inserted = 0
    updated = 0

    for item in unique_items:
        dedupe_hash = str(item["dedupe_hash"])
        row = existing_by_hash.get(dedupe_hash)

        if row is None:
            row = NewsItem(
                company_id=company_id,
                ticker=ticker.upper(),
                source_name=str(item["source_name"]),
                publisher=_optional_str(item.get("publisher")),
                headline=str(item["headline"]),
                summary=_optional_str(item.get("summary")),
                url=str(item["url"]),
                published_at=item["published_at"],
                retrieved_at=item.get("retrieved_at") or datetime.now(timezone.utc),
                dedupe_hash=dedupe_hash,
                sentiment_label=_optional_str(item.get("sentiment_label")),
                raw_json=item.get("raw_json")
                if isinstance(item.get("raw_json"), dict)
                else None,
            )
            db.add(row)
            inserted += 1
            continue

        row.ticker = ticker.upper()
        row.source_name = str(item["source_name"])
        row.publisher = _optional_str(item.get("publisher"))
        row.headline = str(item["headline"])
        row.summary = _optional_str(item.get("summary"))
        row.url = str(item["url"])
        row.published_at = item["published_at"]
        row.retrieved_at = item.get("retrieved_at") or datetime.now(timezone.utc)
        row.sentiment_label = _optional_str(item.get("sentiment_label"))
        row.raw_json = item.get("raw_json") if isinstance(item.get("raw_json"), dict) else None
        updated += 1

    db.flush()

    return {
        "selected": len(items),
        "deduped_in_batch": len(items) - len(unique_items),
        "inserted": inserted,
        "updated": updated,
        "stored": inserted + updated,
    }


def _dedupe_batch(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    by_hash: dict[str, Mapping[str, Any]] = {}

    for item in items:
        dedupe_hash = item.get("dedupe_hash")
        if not dedupe_hash:
            continue
        by_hash[str(dedupe_hash)] = item

    return list(by_hash.values())


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
