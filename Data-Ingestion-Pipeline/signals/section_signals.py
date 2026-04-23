from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from signals.history import get_previous_comparable_filing
from signals.text_signals import (
    TEXT_SIGNAL_MODEL_VERSION,
    compute_and_store_section_signals,
    compute_and_store_text_signals,
    compute_section_drift_signals,
    compute_text_signals,
)

DEFAULT_SIGNAL_MODEL_VERSION = TEXT_SIGNAL_MODEL_VERSION


def get_previous_filing(
    db: Session,
    *,
    company_id: int,
    form_type: str,
    current_filed_at,
    current_filing_id: int,
) -> Filing | None:
    return db.scalar(
        select(Filing)
        .where(
            Filing.company_id == company_id,
            Filing.form_type == form_type,
            or_(
                Filing.filed_at < current_filed_at,
                and_(Filing.filed_at == current_filed_at, Filing.id < current_filing_id),
            ),
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )


__all__ = [
    "DEFAULT_SIGNAL_MODEL_VERSION",
    "compute_and_store_section_signals",
    "compute_and_store_text_signals",
    "compute_section_drift_signals",
    "compute_text_signals",
    "get_previous_comparable_filing",
    "get_previous_filing",
]
