"""
macro_repo.py

Database read/write helpers for macro_observations. Handles rerun-safe
observation upserts keyed by series, observation date, and provider.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.macro_observation import MacroObservation


def upsert_macro_observations(
    db: Session,
    *,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    unique_rows = _dedupe_batch(rows)
    existing_by_key = _load_existing_rows(db, unique_rows)

    inserted = 0
    updated = 0

    for row_data in unique_rows:
        key = (
            str(row_data["series_id"]),
            row_data["observation_date"],
            str(row_data["provider"]),
        )
        row = existing_by_key.get(key)

        if row is None:
            row = MacroObservation(
                series_id=str(row_data["series_id"]),
                observation_date=row_data["observation_date"],
                value=_to_decimal(row_data.get("value")),
                provider=str(row_data["provider"]),
                retrieved_at=row_data.get("retrieved_at") or datetime.now(timezone.utc),
                frequency=_optional_str(row_data.get("frequency")),
                units=_optional_str(row_data.get("units")),
                title=_optional_str(row_data.get("title")),
            )
            db.add(row)
            inserted += 1
            continue

        row.value = _to_decimal(row_data.get("value"))
        row.retrieved_at = row_data.get("retrieved_at") or datetime.now(timezone.utc)
        row.frequency = _optional_str(row_data.get("frequency"))
        row.units = _optional_str(row_data.get("units"))
        row.title = _optional_str(row_data.get("title"))
        updated += 1

    db.flush()

    return {
        "selected": len(rows),
        "deduped_in_batch": len(rows) - len(unique_rows),
        "inserted": inserted,
        "updated": updated,
        "stored": inserted + updated,
    }


def _load_existing_rows(
    db: Session,
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, Any, str], MacroObservation]:
    date_ranges_by_series: dict[tuple[str, str], list[Any]] = defaultdict(list)

    for row in rows:
        date_ranges_by_series[
            (
                str(row["series_id"]),
                str(row["provider"]),
            )
        ].append(row["observation_date"])

    existing_by_key: dict[tuple[str, Any, str], MacroObservation] = {}

    for (series_id, provider), observation_dates in date_ranges_by_series.items():
        existing_rows = db.scalars(
            select(MacroObservation).where(
                MacroObservation.series_id == series_id,
                MacroObservation.provider == provider,
                MacroObservation.observation_date >= min(observation_dates),
                MacroObservation.observation_date <= max(observation_dates),
            )
        ).all()

        for row in existing_rows:
            existing_by_key[(row.series_id, row.observation_date, row.provider)] = row

    return existing_by_key


def _dedupe_batch(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    by_key: dict[tuple[Any, Any, Any], Mapping[str, Any]] = {}

    for row in rows:
        series_id = row.get("series_id")
        observation_date = row.get("observation_date")
        provider = row.get("provider")
        if not series_id or observation_date is None or not provider:
            continue
        by_key[(series_id, observation_date, provider)] = row

    return list(by_key.values())


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
