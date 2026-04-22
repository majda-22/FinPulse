from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    FilingSnapshot,
    InsiderSummary,
    MarketSnapshot,
    NewsItem,
    ScoreResponse,
    SignalRow,
    XbrlSummary,
)
from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.insider_transaction import InsiderTransaction
from app.db.models.market_price import MarketPrice
from app.db.models.news_item import NewsItem as NewsItemModel
from app.db.models.signal_score import SignalScore
from app.db.models.xbrl_fact import XbrlFact
from app.db.session import get_db_dependency
from signals.xbrl_features import CANONICAL_FACT_ALIASES

router = APIRouter()

XBRL_SUMMARY_FACTS: dict[str, tuple[str, ...]] = {
    "revenue": CANONICAL_FACT_ALIASES["revenue"],
    "net_income": CANONICAL_FACT_ALIASES["net_income"],
    "gross_profit": CANONICAL_FACT_ALIASES["gross_profit"],
    "operating_income": CANONICAL_FACT_ALIASES["operating_income"],
    "total_assets": CANONICAL_FACT_ALIASES["assets"],
    "total_debt": CANONICAL_FACT_ALIASES["long_term_debt"],
}
SCORE_SCALAR_FIELDS = (
    "companies.name",
    "companies.ticker",
    "companies.nci_global",
    "filings.filed_at",
    "filings.latest_annual_filed_at",
    "filings.latest_quarterly_filed_at",
    "market_prices.price_close",
    "news_items.sentiment_score",
)


@router.get(
    "/{ticker}_get_{field_name}",
    status_code=status.HTTP_200_OK,
)
def get_score_scalar_alias(
    ticker: str,
    field_name: str,
    db: Session = Depends(get_db_dependency),
) -> Any:
    return _extract_score_scalar(db, ticker=ticker, field_name=field_name)


@router.get(
    "/{ticker}/value/{field_name}",
    status_code=status.HTTP_200_OK,
)
def get_score_scalar(
    ticker: str,
    field_name: str,
    db: Session = Depends(get_db_dependency),
) -> Any:
    return _extract_score_scalar(db, ticker=ticker, field_name=field_name)


@router.get(
    "/{ticker}",
    response_model=ScoreResponse,
    status_code=status.HTTP_200_OK,
)
def get_score(
    ticker: str,
    db: Session = Depends(get_db_dependency),
) -> ScoreResponse:
    return _build_score_response(db, ticker)


def _build_score_response(db: Session, ticker: str) -> ScoreResponse:
    company = _get_company_or_404(db, ticker)

    latest_annual = _get_latest_filing_snapshot(db, company.id, ("10-K", "10-K/A"))
    latest_quarterly = _get_latest_filing_snapshot(db, company.id, ("10-Q", "10-Q/A"))
    latest_signals = _get_latest_signals(db, company.id)

    composite_signal = next(
        (
            signal
            for signal in latest_signals
            if signal.signal_name in {"nci_global", "composite_filing_risk"}
        ),
        None,
    )
    composite_score = composite_signal.signal_value if composite_signal is not None else None

    xbrl_summary = _get_xbrl_summary(db, company.id)
    insider_summary = _get_insider_summary(db, company.id)
    market_snapshot = _get_market_snapshot(db, company.id)
    recent_news = _get_recent_news(db, company.id)

    latest_filing_date = max(
        [item.filed_at for item in (latest_annual, latest_quarterly) if item is not None],
        default=None,
    )

    data_freshness = {
        "filings_days_old": _days_old(latest_filing_date),
        "xbrl_days_old": _days_old(xbrl_summary.period_end if xbrl_summary is not None else None),
        "market_days_old": _days_old(market_snapshot.price_date),
        "news_days_old": _days_old(recent_news[0].published_at if recent_news else None),
        "signals_days_old": _days_old(composite_signal.computed_at if composite_signal is not None else None),
    }

    return ScoreResponse(
        ticker=company.ticker,
        company_name=company.name,
        sector=company.sector,
        composite_risk_score=composite_score,
        risk_label=_risk_label(composite_score),
        latest_annual_filing=latest_annual,
        latest_quarterly_filing=latest_quarterly,
        signals=latest_signals,
        xbrl_summary=xbrl_summary,
        insider_summary=insider_summary,
        market=market_snapshot,
        recent_news=recent_news,
        data_freshness=data_freshness,
        scored_at=composite_signal.computed_at if composite_signal is not None else None,
    )


def _extract_score_scalar(db: Session, *, ticker: str, field_name: str) -> Any:
    score_response = _build_score_response(db, ticker)
    latest_filed_at = _latest_filing_date(
        score_response.latest_annual_filing,
        score_response.latest_quarterly_filing,
    )

    resolvers = {
        "companies.name": lambda: score_response.company_name,
        "companies.ticker": lambda: score_response.ticker,
        "companies.nci_global": lambda: score_response.composite_risk_score,
        "filings.filed_at": lambda: latest_filed_at,
        "filings.latest_annual_filed_at": lambda: (
            score_response.latest_annual_filing.filed_at
            if score_response.latest_annual_filing is not None
            else None
        ),
        "filings.latest_quarterly_filed_at": lambda: (
            score_response.latest_quarterly_filing.filed_at
            if score_response.latest_quarterly_filing is not None
            else None
        ),
        "market_prices.price_close": lambda: score_response.market.close_price,
        "news_items.sentiment_score": lambda: (
            score_response.recent_news[0].sentiment_score
            if score_response.recent_news
            else None
        ),
    }

    resolver = resolvers.get(field_name)
    if resolver is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": f"Unsupported scalar field {field_name!r}",
                "supported_fields": list(SCORE_SCALAR_FIELDS),
            },
        )
    return resolver()


def _get_company_or_404(db: Session, ticker: str) -> Company:
    identifier = " ".join(ticker.split()).strip()
    normalized_ticker = identifier.upper()
    normalized_cik = identifier.zfill(10) if identifier.isdigit() else None

    company = None
    if normalized_cik is not None:
        company = db.scalar(
            select(Company).where(Company.cik == normalized_cik)
        )
    if company is None:
        company = db.scalar(
            select(Company).where(Company.ticker == normalized_ticker)
        )
    if company is None:
        company = db.scalar(
            select(Company).where(func.lower(Company.name) == identifier.lower())
        )
    if company is None and identifier:
        partial_matches = db.scalars(
            select(Company)
            .where(Company.name.ilike(f"%{identifier}%"))
            .order_by(Company.name.asc())
            .limit(2)
        ).all()
        if len(partial_matches) == 1:
            company = partial_matches[0]
        elif len(partial_matches) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": f"Company identifier {identifier!r} matched multiple companies.",
                    "candidates": [
                        {
                            "name": match.name,
                            "ticker": match.ticker,
                            "cik": match.cik,
                        }
                        for match in partial_matches
                    ],
                },
            )

    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Company identifier {identifier!r} was not found in the database. "
                "You can use ticker, full company name, or CIK. "
                "Run the ingestion pipeline for this company first if needed."
            ),
        )
    return company


def _get_latest_filing_snapshot(
    db: Session,
    company_id: int,
    form_types: tuple[str, ...],
) -> FilingSnapshot | None:
    filing = db.scalar(
        select(Filing)
        .where(
            Filing.company_id == company_id,
            Filing.form_type.in_(form_types),
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(1)
    )
    if filing is None:
        return None
    return _filing_snapshot_from_row(filing)


def _get_latest_signals(db: Session, company_id: int) -> list[SignalRow]:
    rows = db.execute(
        select(SignalScore, Filing)
        .join(Filing, Filing.id == SignalScore.filing_id)
        .where(SignalScore.company_id == company_id)
        .order_by(SignalScore.computed_at.desc(), Filing.filed_at.desc(), Filing.id.desc())
    ).all()

    latest_by_name: dict[str, SignalRow] = {}
    for signal_row, filing in rows:
        signal_name = signal_row.signal_name or "unknown"
        if signal_name in latest_by_name:
            continue
        latest_by_name[signal_name] = _build_signal_row(signal_row, filing)

    return sorted(
        latest_by_name.values(),
        key=lambda row: (row.computed_at, row.signal_name),
        reverse=True,
    )


def _get_xbrl_summary(db: Session, company_id: int) -> XbrlSummary | None:
    latest_period_end = db.scalar(
        select(func.max(XbrlFact.period_end)).where(XbrlFact.company_id == company_id)
    )
    if latest_period_end is None:
        return None

    all_concepts = {
        concept
        for aliases in XBRL_SUMMARY_FACTS.values()
        for concept in aliases
    }
    rows = db.scalars(
        select(XbrlFact)
        .where(
            XbrlFact.company_id == company_id,
            XbrlFact.period_end == latest_period_end,
            XbrlFact.concept.in_(all_concepts),
        )
        .order_by(XbrlFact.created_at.desc(), XbrlFact.id.desc())
    ).all()

    summary_values: dict[str, float | None] = {}
    for name, aliases in XBRL_SUMMARY_FACTS.items():
        summary_values[name] = _select_fact_value(rows, aliases)

    return XbrlSummary(
        revenue=summary_values["revenue"],
        net_income=summary_values["net_income"],
        gross_profit=summary_values["gross_profit"],
        operating_income=summary_values["operating_income"],
        total_assets=summary_values["total_assets"],
        total_debt=summary_values["total_debt"],
        period_end=latest_period_end,
    )


def _get_insider_summary(db: Session, company_id: int) -> InsiderSummary:
    total_transactions = db.scalar(
        select(func.count())
        .select_from(InsiderTransaction)
        .where(InsiderTransaction.company_id == company_id)
    ) or 0

    opportunistic_sells = db.scalar(
        select(func.count())
        .select_from(InsiderTransaction)
        .where(
            InsiderTransaction.company_id == company_id,
            InsiderTransaction.transaction_type_normalized == "open_market_sell",
        )
    ) or 0

    total_sell_value = db.scalar(
        select(func.coalesce(func.sum(InsiderTransaction.transaction_value), 0))
        .where(
            InsiderTransaction.company_id == company_id,
            InsiderTransaction.transaction_code == "S",
        )
    ) or Decimal("0")

    total_buy_value = db.scalar(
        select(func.coalesce(func.sum(InsiderTransaction.transaction_value), 0))
        .where(
            InsiderTransaction.company_id == company_id,
            InsiderTransaction.transaction_code == "P",
        )
    ) or Decimal("0")

    latest_transaction_date = db.scalar(
        select(func.max(InsiderTransaction.transaction_date)).where(
            InsiderTransaction.company_id == company_id
        )
    )

    return InsiderSummary(
        total_transactions=int(total_transactions),
        opportunistic_sells=int(opportunistic_sells),
        total_sell_value=float(total_sell_value),
        total_buy_value=float(total_buy_value),
        latest_transaction_date=latest_transaction_date,
    )


def _get_market_snapshot(db: Session, company_id: int) -> MarketSnapshot:
    row = db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id)
        .order_by(MarketPrice.trading_date.desc(), MarketPrice.id.desc())
        .limit(1)
    )
    if row is None:
        return MarketSnapshot(close_price=None, volume=None, price_date=None)

    return MarketSnapshot(
        close_price=float(row.close) if row.close is not None else None,
        volume=float(row.volume) if row.volume is not None else None,
        price_date=row.trading_date,
    )


def _get_recent_news(db: Session, company_id: int) -> list[NewsItem]:
    rows = db.scalars(
        select(NewsItemModel)
        .where(NewsItemModel.company_id == company_id)
        .order_by(NewsItemModel.published_at.desc(), NewsItemModel.id.desc())
        .limit(5)
    ).all()

    items: list[NewsItem] = []
    for row in rows:
        source = row.publisher or row.source_name
        sentiment_score = None
        if isinstance(row.raw_json, dict):
            raw_score = row.raw_json.get("sentiment_score")
            if isinstance(raw_score, (int, float)):
                sentiment_score = float(raw_score)

        items.append(
            NewsItem(
                headline=row.headline,
                source=source,
                published_at=row.published_at,
                sentiment_score=sentiment_score,
            )
        )

    return items


def _filing_snapshot_from_row(filing: Filing) -> FilingSnapshot:
    return FilingSnapshot(
        id=filing.id,
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        filed_at=filing.filed_at,
        period_of_report=filing.period_of_report,
        is_extracted=filing.is_extracted,
        is_xbrl_parsed=filing.is_xbrl_parsed,
        is_embedded=filing.is_embedded,
        is_signal_scored=filing.is_signal_scored,
        processing_status=filing.processing_status,
    )


def _build_signal_row(signal_row: SignalScore, filing: Filing) -> SignalRow:
    detail = _normalize_detail(signal_row.detail)
    signal_value = float(signal_row.signal_value) if signal_row.signal_value is not None else None
    return SignalRow(
        signal_name=signal_row.signal_name or "unknown",
        signal_value=signal_value,
        status=_signal_status(signal_value, detail),
        detail=detail,
        computed_at=signal_row.computed_at,
        filing_id=filing.id,
        form_type=filing.form_type,
        filed_at=filing.filed_at,
    )


def _normalize_detail(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, list):
        return {"items": detail}
    return {}


def _signal_status(signal_value: float | None, detail: dict[str, Any]) -> str:
    if isinstance(detail.get("status"), str) and detail["status"].strip():
        return str(detail["status"]).strip()
    if isinstance(detail.get("label"), str) and detail["label"].strip():
        return str(detail["label"]).strip()
    return _risk_label(signal_value).lower()


def _risk_label(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score < 0.3:
        return "LOW"
    if score < 0.5:
        return "MEDIUM"
    if score < 0.75:
        return "HIGH"
    return "CRITICAL"


def _latest_filing_date(
    latest_annual: FilingSnapshot | None,
    latest_quarterly: FilingSnapshot | None,
) -> date | None:
    return max(
        [item.filed_at for item in (latest_annual, latest_quarterly) if item is not None],
        default=None,
    )


def _select_fact_value(rows: list[XbrlFact], aliases: tuple[str, ...]) -> float | None:
    alias_rank = {alias: index for index, alias in enumerate(aliases)}
    matches = [row for row in rows if row.concept in aliases and row.value is not None]
    if not matches:
        return None
    matches.sort(key=lambda row: alias_rank.get(row.concept, len(alias_rank)))
    return float(matches[0].value) if matches[0].value is not None else None


def _days_old(value: date | datetime | None) -> int | None:
    if value is None:
        return None

    now = datetime.now(timezone.utc)
    if isinstance(value, datetime):
        target_date = value.astimezone(timezone.utc).date()
    else:
        target_date = value

    return max((now.date() - target_date).days, 0)
