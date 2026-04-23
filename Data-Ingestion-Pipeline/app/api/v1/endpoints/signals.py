from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas import SignalHistoryPoint, SignalRow
from app.api.v1.endpoints.score import _build_signal_row, _get_company_or_404
from app.db.models.filing import Filing
from app.db.models.signal_score import SignalScore
from app.db.session import get_db_dependency

router = APIRouter()


@router.get(
    "/{ticker}",
    response_model=list[SignalRow],
    status_code=status.HTTP_200_OK,
)
def get_signals(
    ticker: str,
    signal_name: str | None = Query(default=None),
    form_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db_dependency),
) -> list[SignalRow]:
    company = _get_company_or_404(db, ticker)

    query = (
        select(SignalScore, Filing)
        .join(Filing, Filing.id == SignalScore.filing_id)
        .where(SignalScore.company_id == company.id)
    )

    if signal_name:
        query = query.where(SignalScore.signal_name == signal_name)
    if form_type:
        query = query.where(Filing.form_type == form_type.upper())

    rows = db.execute(
        query.order_by(Filing.filed_at.desc(), SignalScore.computed_at.desc(), SignalScore.id.desc()).limit(limit)
    ).all()

    return [_build_signal_row(signal_row, filing) for signal_row, filing in rows]


@router.get(
    "/{ticker}/history",
    response_model=list[SignalHistoryPoint],
    status_code=status.HTTP_200_OK,
)
def get_signal_history(
    ticker: str,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_dependency),
) -> list[SignalHistoryPoint]:
    company = _get_company_or_404(db, ticker)

    rows = db.execute(
        select(SignalScore, Filing)
        .join(Filing, Filing.id == SignalScore.filing_id)
        .where(
            SignalScore.company_id == company.id,
            SignalScore.signal_name == "composite_filing_risk",
        )
        .order_by(Filing.filed_at.asc(), Filing.id.asc(), SignalScore.computed_at.asc())
        .limit(limit)
    ).all()

    return [
        SignalHistoryPoint(
            filing_id=filing.id,
            accession_number=filing.accession_number,
            form_type=filing.form_type,
            filed_at=filing.filed_at,
            period_of_report=filing.period_of_report,
            signal_value=float(signal_row.signal_value) if signal_row.signal_value is not None else None,
            computed_at=signal_row.computed_at,
        )
        for signal_row, filing in rows
    ]
