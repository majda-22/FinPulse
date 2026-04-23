"""
market_repo.py

Database read/write helpers for market_prices. Handles rerun-safe daily-bar
upserts keyed by company, trading date, and provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.db.models.market_price import MarketPrice


def upsert_market_prices(
    db: Session,
    *,
    company_id: int,
    ticker: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    unique_rows = _dedupe_batch(rows)
    unique_keys = [
        (company_id, row["trading_date"], str(row["provider"]))
        for row in unique_rows
    ]

    existing_rows = db.scalars(
        select(MarketPrice).where(
            tuple_(
                MarketPrice.company_id,
                MarketPrice.trading_date,
                MarketPrice.provider,
            ).in_(unique_keys)
        )
    ).all() if unique_keys else []
    existing_by_key = {
        (row.company_id, row.trading_date, row.provider): row for row in existing_rows
    }

    inserted = 0
    updated = 0

    for row_data in unique_rows:
        key = (company_id, row_data["trading_date"], str(row_data["provider"]))
        row = existing_by_key.get(key)

        if row is None:
            row = MarketPrice(
                company_id=company_id,
                ticker=ticker.upper(),
                trading_date=row_data["trading_date"],
                open=_to_decimal(row_data.get("open")),
                high=_to_decimal(row_data.get("high")),
                low=_to_decimal(row_data.get("low")),
                close=_to_decimal(row_data.get("close")),
                adjusted_close=_to_decimal(row_data.get("adjusted_close")),
                volume=_to_int(row_data.get("volume")),
                provider=str(row_data["provider"]),
                retrieved_at=row_data.get("retrieved_at") or datetime.now(timezone.utc),
            )
            db.add(row)
            inserted += 1
            continue

        row.ticker = ticker.upper()
        row.open = _to_decimal(row_data.get("open"))
        row.high = _to_decimal(row_data.get("high"))
        row.low = _to_decimal(row_data.get("low"))
        row.close = _to_decimal(row_data.get("close"))
        row.adjusted_close = _to_decimal(row_data.get("adjusted_close"))
        row.volume = _to_int(row_data.get("volume"))
        row.retrieved_at = row_data.get("retrieved_at") or datetime.now(timezone.utc)
        updated += 1

    db.flush()

    return {
        "selected": len(rows),
        "deduped_in_batch": len(rows) - len(unique_rows),
        "inserted": inserted,
        "updated": updated,
        "stored": inserted + updated,
    }


def _dedupe_batch(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    by_key: dict[tuple[Any, Any], Mapping[str, Any]] = {}

    for row in rows:
        trading_date = row.get("trading_date")
        provider = row.get("provider")
        if trading_date is None or provider is None:
            continue
        by_key[(trading_date, provider)] = row

    return list(by_key.values())


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
