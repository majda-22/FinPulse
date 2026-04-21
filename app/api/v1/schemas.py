from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SignalRow(BaseModel):
    signal_name: str
    signal_value: float | None
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime
    filing_id: int | None = None
    form_type: str | None = None
    filed_at: date | None = None


class FilingSnapshot(BaseModel):
    id: int
    accession_number: str
    form_type: str
    filed_at: date
    period_of_report: date | None
    is_extracted: bool
    is_xbrl_parsed: bool
    is_embedded: bool
    is_signal_scored: bool
    processing_status: str


class XbrlSummary(BaseModel):
    revenue: float | None
    net_income: float | None
    gross_profit: float | None
    operating_income: float | None
    total_assets: float | None
    total_debt: float | None
    period_end: date


class InsiderSummary(BaseModel):
    total_transactions: int
    opportunistic_sells: int
    total_sell_value: float
    total_buy_value: float
    latest_transaction_date: date | None


class MarketSnapshot(BaseModel):
    close_price: float | None
    volume: float | None
    price_date: date | None


class NewsItem(BaseModel):
    headline: str
    source: str
    published_at: datetime
    sentiment_score: float | None


class EmbeddingRow(BaseModel):
    id: int
    filing_id: int
    filing_section_id: int
    accession_number: str
    form_type: str
    filed_at: date
    section: str
    chunk_idx: int
    text: str
    embedding: list[float] | None
    provider: str
    embedding_model: str
    reconstruction_error: float | None
    anomaly_score: float | None
    created_at: datetime


class ScoreResponse(BaseModel):
    ticker: str
    company_name: str
    sector: str | None
    composite_risk_score: float | None
    risk_label: str
    latest_annual_filing: FilingSnapshot | None
    latest_quarterly_filing: FilingSnapshot | None
    signals: list[SignalRow]
    xbrl_summary: XbrlSummary | None
    insider_summary: InsiderSummary
    market: MarketSnapshot
    recent_news: list[NewsItem]
    data_freshness: dict[str, int | None]
    scored_at: datetime | None


class SignalHistoryPoint(BaseModel):
    filing_id: int
    accession_number: str
    form_type: str
    filed_at: date
    period_of_report: date | None
    signal_value: float | None
    computed_at: datetime


class HealthResponse(BaseModel):
    status: str
    db: str
    version: str
