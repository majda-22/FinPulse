from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.signal_score import SignalScore


def upsert_signal_scores(db: Session, signals: list[Mapping[str, Any]]) -> list[SignalScore]:
    rows: list[SignalScore] = []

    for signal in signals:
        signal_name = signal["signal_name"]
        filing_id = signal["filing_id"]
        existing = db.scalar(
            select(SignalScore).where(
                SignalScore.filing_id == filing_id,
                SignalScore.signal_name == signal_name,
            )
        )

        computed_at = signal.get("computed_at") or datetime.now(timezone.utc)

        if existing is None:
            existing = SignalScore(
                filing_id=filing_id,
                company_id=signal["company_id"],
                signal_name=signal_name,
                signal_value=signal.get("signal_value"),
                detail=_json_safe(signal.get("detail")),
                model_version=signal.get("model_version"),
                computed_at=computed_at,
            )
            db.add(existing)
        else:
            if existing.company_id != signal["company_id"]:
                raise ValueError(
                    f"Signal {signal_name!r} for filing_id={filing_id} already belongs "
                    f"to company_id={existing.company_id}, not {signal['company_id']}"
                )
            existing.signal_value = signal.get("signal_value")
            existing.detail = _json_safe(signal.get("detail"))
            existing.model_version = signal.get("model_version")
            existing.computed_at = computed_at

        rows.append(existing)

    db.flush()
    return rows


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def mark_signal_stage(
    filing: Filing,
    *,
    text_scored: bool = False,
    numeric_scored: bool = False,
    insider_scored: bool = False,
    composite_scored: bool = False,
    processing_status: str | None = None,
) -> None:
    if text_scored:
        filing.is_text_signal_scored = True
    if numeric_scored:
        filing.is_numeric_signal_scored = True
    if insider_scored:
        filing.is_insider_signal_scored = True
    if composite_scored:
        filing.is_composite_signal_scored = True

    filing.is_signal_scored = (
        filing.is_text_signal_scored
        and filing.is_numeric_signal_scored
        and filing.is_insider_signal_scored
        and filing.is_composite_signal_scored
    )

    if processing_status is not None:
        filing.processing_status = processing_status
