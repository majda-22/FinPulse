from __future__ import annotations

from collections.abc import Mapping
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.signal_score import SignalScore


def load_signal_rows_by_name(
    db: Session,
    *,
    filing_id: int,
    signal_names: Iterable[str] | None = None,
    model_version: str | None = None,
    model_versions: Mapping[str, str] | None = None,
    latest_only: bool = True,
) -> dict[str, SignalScore]:
    query = (
        select(SignalScore)
        .where(SignalScore.filing_id == filing_id)
        .order_by(SignalScore.signal_name.asc(), SignalScore.computed_at.desc(), SignalScore.id.desc())
    )
    if signal_names is not None:
        names = list(signal_names)
        if not names:
            return {}
        query = query.where(SignalScore.signal_name.in_(names))
    if model_version is not None:
        query = query.where(SignalScore.model_version == model_version)

    rows = db.scalars(query).all()
    result: dict[str, SignalScore] = {}
    for row in rows:
        if row.signal_name is None:
            continue
        if model_versions is not None:
            expected_version = model_versions.get(row.signal_name)
            if expected_version is not None and row.model_version != expected_version:
                continue
        if latest_only and row.signal_name in result:
            continue
        result[row.signal_name] = row
    return result


def load_signal_values_by_name(
    db: Session,
    *,
    filing_id: int,
    signal_names: Iterable[str] | None = None,
    model_version: str | None = None,
    model_versions: Mapping[str, str] | None = None,
    latest_only: bool = True,
) -> dict[str, float | None]:
    rows = load_signal_rows_by_name(
        db,
        filing_id=filing_id,
        signal_names=signal_names,
        model_version=model_version,
        model_versions=model_versions,
        latest_only=latest_only,
    )
    return {
        signal_name: row.signal_value
        for signal_name, row in rows.items()
    }
