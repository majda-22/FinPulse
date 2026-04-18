"""
ingestion/company_repo.py — database read/write for companies and filings.

All DB logic lives here. Pipeline scripts call these functions,
never writing SQL directly.
"""

import logging
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.pipeline_event import PipelineEvent
from ingestion.edgar_client import CompanyMeta, FilingMeta

logger = logging.getLogger(__name__)


# ── Company ───────────────────────────────────────────────────────────────────

def upsert_company(db: Session, meta: CompanyMeta) -> Company:
    """
    Insert a new company or update an existing one by CIK.
    Returns the Company ORM object.
    """
    company = db.scalar(select(Company).where(Company.cik == meta.cik))

    if company is None:
        company = Company(
            cik=meta.cik,
            ticker=meta.ticker.upper(),
            name=meta.name,
            sic_code=meta.sic_code,
            sic_description=meta.sic_description,
            exchange=meta.exchange,
        )
        db.add(company)
        logger.info("Inserted new company: %s (%s)", meta.ticker, meta.cik)
    else:
        company.ticker = meta.ticker.upper()
        company.name = meta.name
        company.sic_code = meta.sic_code or company.sic_code
        company.sic_description = meta.sic_description or company.sic_description
        company.exchange = meta.exchange or company.exchange
        logger.debug("Updated existing company: %s", meta.ticker)

    db.flush()
    return company


def get_company_by_ticker(db: Session, ticker: str) -> Optional[Company]:
    return db.scalar(select(Company).where(Company.ticker == ticker.upper()))


def get_company_by_cik(db: Session, cik: str) -> Optional[Company]:
    return db.scalar(select(Company).where(Company.cik == cik))


# ── Filing ────────────────────────────────────────────────────────────────────

def insert_filing(
    db: Session,
    company_id: int,
    meta: FilingMeta,
    s3_key: str,
    file_size: Optional[int] = None,
) -> tuple[Filing, bool]:
    """
    Insert a filing row. Returns (filing, created).
    If accession_number already exists, returns the existing row
    and created=False.
    """
    existing = db.scalar(
        select(Filing).where(Filing.accession_number == meta.accession_number)
    )
    if existing:
        logger.debug("Filing already exists: %s", meta.accession_number)
        return existing, False

    fiscal_year = meta.period_of_report.year if meta.period_of_report else None
    fiscal_quarter = _quarter(meta.period_of_report) if meta.period_of_report else None

    filing = Filing(
        company_id=company_id,
        accession_number=meta.accession_number,
        form_type=meta.form_type,
        filed_at=meta.filed_at,
        period_of_report=meta.period_of_report,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        raw_s3_key=s3_key,
        raw_size_bytes=file_size,
    )
    db.add(filing)
    db.flush()

    logger.info(
        "Inserted filing: %s (%s %s)",
        meta.accession_number,
        meta.form_type,
        meta.filed_at,
    )
    return filing, True


def get_filing_by_accession(db: Session, accession: str) -> Optional[Filing]:
    return db.scalar(select(Filing).where(Filing.accession_number == accession))


def mark_filing_extracted(db: Session, filing_id: int) -> None:
    filing = db.get(Filing, filing_id)
    if filing:
        filing.is_extracted = True
        db.flush()


def mark_filing_xbrl_parsed(db: Session, filing_id: int) -> None:
    filing = db.get(Filing, filing_id)
    if filing:
        filing.is_xbrl_parsed = True
        db.flush()


# ── Pipeline events ───────────────────────────────────────────────────────────

def log_event(
    db: Session,
    event_type: str,
    layer: str,
    company_id: Optional[int] = None,
    filing_id: Optional[int] = None,
    duration_ms: Optional[int] = None,
    detail: Optional[dict] = None,
) -> PipelineEvent:
    """
    Append an immutable audit event.
    """
    event = PipelineEvent(
        event_type=event_type,
        layer=layer,
        company_id=company_id,
        filing_id=filing_id,
        duration_ms=duration_ms,
        detail=detail or {},
    )
    db.add(event)
    db.flush()
    return event


# ── Helpers ───────────────────────────────────────────────────────────────────

def _quarter(d: date) -> int:
    return (d.month - 1) // 3 + 1