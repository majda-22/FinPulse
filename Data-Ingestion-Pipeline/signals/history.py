from __future__ import annotations

from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing


ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}


def infer_fiscal_quarter(filing: Filing) -> int | None:
    if filing.fiscal_quarter is not None:
        return int(filing.fiscal_quarter)
    if filing.period_of_report is None:
        return None
    return ((filing.period_of_report.month - 1) // 3) + 1


def load_comparable_filing_history(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
) -> list[Filing]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    base_query = (
        select(Filing)
        .where(
            Filing.company_id == filing.company_id,
            or_(
                Filing.filed_at < filing.filed_at,
                and_(Filing.filed_at == filing.filed_at, Filing.id <= filing.id),
            ),
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
    )

    if filing.form_type in ANNUAL_FORMS:
        rows = db.scalars(base_query.where(Filing.form_type.in_(ANNUAL_FORMS)).limit(history_limit)).all()
        return list(reversed(rows))

    if filing.form_type in QUARTERLY_FORMS:
        candidates = db.scalars(base_query.where(Filing.form_type.in_(QUARTERLY_FORMS)).limit(max(history_limit * 4, 24))).all()
        target_quarter = infer_fiscal_quarter(filing)
        if target_quarter is not None:
            quarter_rows = [row for row in candidates if infer_fiscal_quarter(row) == target_quarter]
            if len(quarter_rows) >= 2:
                return list(reversed(quarter_rows[:history_limit]))
        return list(reversed(candidates[:history_limit]))

    rows = db.scalars(base_query.where(Filing.form_type == filing.form_type).limit(history_limit)).all()
    return list(reversed(rows))


def get_previous_comparable_filing(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
) -> Filing | None:
    history = load_comparable_filing_history(db, filing_id=filing_id, history_limit=history_limit)
    if len(history) < 2:
        return None
    return history[-2]


def history_depth_before_current(history: list[Filing]) -> int:
    return max(len(history) - 1, 0)


def period_end_or_filed_at(filing: Filing) -> date:
    return filing.period_of_report or filing.filed_at

