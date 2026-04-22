from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.schemas import CompanyIdentity
from app.db.models.company import Company
from app.db.session import get_db_dependency

router = APIRouter()


@router.get(
    "",
    response_model=list[CompanyIdentity],
    status_code=status.HTTP_200_OK,
)
def get_companies(
    active_only: bool = Query(default=False),
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db_dependency),
) -> list[CompanyIdentity]:
    query = select(Company)
    if active_only:
        query = query.where(Company.is_active.is_(True))

    rows = db.scalars(
        query.order_by(Company.name.asc()).limit(limit)
    ).all()
    return [
        CompanyIdentity(
            name=row.name,
            ticker=row.ticker,
            cik=row.cik,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.get(
    "/ticker-by-name",
    response_model=str,
    status_code=status.HTTP_200_OK,
)
def get_ticker_by_company_name(
    name: str = Query(..., min_length=1),
    db: Session = Depends(get_db_dependency),
) -> str:
    normalized_name = " ".join(name.split()).strip()

    exact_match = db.scalar(
        select(Company.ticker).where(func.lower(Company.name) == normalized_name.lower())
    )
    if exact_match:
        return exact_match

    partial_matches = db.execute(
        select(Company.name, Company.ticker)
        .where(Company.name.ilike(f"%{normalized_name}%"))
        .order_by(Company.name.asc())
        .limit(10)
    ).all()

    if len(partial_matches) == 1:
        return partial_matches[0].ticker

    if not partial_matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No company found matching name {normalized_name!r}.",
        )

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": f"Company name {normalized_name!r} matched multiple companies.",
            "candidates": [
                {"name": company_name, "ticker": ticker}
                for company_name, ticker in partial_matches
            ],
        },
    )


@router.get(
    "/tickers",
    response_model=list[str],
    status_code=status.HTTP_200_OK,
)
def get_company_tickers(
    active_only: bool = Query(default=False),
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db_dependency),
) -> list[str]:
    query = select(Company.ticker)
    if active_only:
        query = query.where(Company.is_active.is_(True))

    rows = db.scalars(
        query.order_by(Company.ticker.asc()).limit(limit)
    ).all()
    return [ticker for ticker in rows if ticker]
