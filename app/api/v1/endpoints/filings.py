from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.score import _filing_snapshot_from_row, _get_company_or_404
from app.api.v1.schemas import FilingSnapshot
from app.db.models.filing import Filing
from app.db.session import get_db_dependency

router = APIRouter()


@router.get(
    "/{ticker}",
    response_model=list[FilingSnapshot],
    status_code=status.HTTP_200_OK,
)
def get_filings(
    ticker: str,
    form_type: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db_dependency),
) -> list[FilingSnapshot]:
    company = _get_company_or_404(db, ticker)

    query = select(Filing).where(Filing.company_id == company.id)
    if form_type:
        query = query.where(Filing.form_type == form_type.upper())

    rows = db.scalars(
        query.order_by(Filing.filed_at.desc(), Filing.id.desc()).limit(limit)
    ).all()

    return [_filing_snapshot_from_row(filing) for filing in rows]
