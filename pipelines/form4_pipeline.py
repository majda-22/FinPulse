"""
form4_pipeline.py

End-to-end pipeline for Form 4 insider data. This pipeline ingests recent
Form 4 filings for one company and parses ownership XML into
insider_transactions.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.session import check_connection, get_db
from ingestion.company_repo import log_event
from ingestion.file_store import FileStore
from ingestion.form4_client import FORM4_FORMS, Form4Client
from pipelines.ingestion_pipeline import ingest_company
from processing.form4_parser import parse_and_store_form4_xml

logger = logging.getLogger("pipelines.form4_pipeline")


async def run_form4_pipeline(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    max_filings: int = 20,
    parse_limit: int = 20,
    skip_ingest: bool = False,
    force_parse: bool = False,
) -> dict[str, Any]:
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    normalized_ticker = ticker.upper().strip() if ticker else None
    normalized_cik = str(cik).strip().zfill(10) if cik else None

    ingest_summary: dict[str, Any] | None = None
    if not skip_ingest:
        ingest_summary = await ingest_company(
            ticker=normalized_ticker,
            cik=normalized_cik,
            form_type="4",
            max_filings=max_filings,
        )

    parse_summary = await parse_pending_form4_filings_async(
        ticker=normalized_ticker,
        cik=normalized_cik,
        limit=parse_limit,
        force=force_parse,
    )

    return {
        "ticker": normalized_ticker,
        "cik": normalized_cik,
        "ingest": ingest_summary,
        "parse": parse_summary,
    }


async def parse_pending_form4_filings_async(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    limit: int = 20,
    force: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    if db is None:
        with get_db() as session:
            return await parse_pending_form4_filings_async(
                ticker=ticker,
                cik=cik,
                limit=limit,
                force=force,
                db=session,
            )

    company = _resolve_company(db, ticker=ticker, cik=cik)
    filings = _load_target_form4_filings(
        db,
        company_id=company.id,
        limit=limit,
        force=force,
    )

    summary: dict[str, Any] = {
        "company_id": company.id,
        "ticker": company.ticker,
        "cik": company.cik,
        "selected": len(filings),
        "processed": 0,
        "failed": 0,
        "stored_transactions": 0,
        "repaired_raw_files": 0,
        "results": [],
    }

    store = FileStore()

    async with Form4Client() as client:
        for filing in filings:
            filing_id = filing.id
            accession_number = filing.accession_number
            try:
                with db.begin_nested():
                    raw_text = store.get(filing.raw_s3_key)
                    xml_text = raw_text

                    if not _looks_like_ownership_xml(raw_text):
                        logger.info(
                            "Stored Form 4 raw file is not ownership XML for filing %d (%s); refetching XML",
                            filing_id,
                            accession_number,
                        )
                        xml_text = await client.get_form4_xml(
                            accession_number=accession_number,
                            cik=company.cik,
                        )
                        store.put(company.cik, accession_number, filing.form_type, xml_text)
                        summary["repaired_raw_files"] += 1

                    result = parse_and_store_form4_xml(
                        filing_id=filing_id,
                        xml_text=xml_text,
                        db=db,
                        source_url=None,
                    )
                summary["processed"] += 1
                summary["stored_transactions"] += result.stored_count
                summary["results"].append(result.to_dict())
            except Exception as exc:
                logger.error(
                    "Failed to parse Form 4 filing %d (%s): %s",
                    filing_id,
                    accession_number,
                    exc,
                )
                failed_filing = db.get(Filing, filing_id)
                if failed_filing is not None:
                    _mark_failed(db, filing=failed_filing, error=str(exc))
                summary["failed"] += 1

    log_event(
        db,
        event_type="form4_parsed",
        layer="processing",
        company_id=company.id,
        detail={
            "step": "form4_pipeline",
            "selected": summary["selected"],
            "processed": summary["processed"],
            "failed": summary["failed"],
            "force": force,
            "repaired_raw_files": summary["repaired_raw_files"],
        },
    )

    return summary


def parse_pending_form4_filings(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    limit: int = 20,
    force: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            parse_pending_form4_filings_async(
                ticker=ticker,
                cik=cik,
                limit=limit,
                force=force,
                db=db,
            )
        )

    raise RuntimeError(
        "parse_pending_form4_filings() cannot be called from an active event loop; "
        "use parse_pending_form4_filings_async() instead"
    )


def _resolve_company(
    db: Session,
    *,
    ticker: str | None,
    cik: str | None,
) -> Company:
    company: Company | None = None

    if ticker is not None:
        company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    elif cik is not None:
        company = db.scalar(select(Company).where(Company.cik == str(cik).strip().zfill(10)))

    if company is None:
        identifier = ticker or cik or "unknown"
        raise RuntimeError(f"Company {identifier!r} not found in database")

    return company


def _load_target_form4_filings(
    db: Session,
    *,
    company_id: int,
    limit: int,
    force: bool,
) -> list[Filing]:
    stmt = (
        select(Filing)
        .where(
            Filing.company_id == company_id,
            Filing.form_type.in_(tuple(sorted(FORM4_FORMS))),
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(limit)
    )

    if not force:
        stmt = stmt.where(Filing.is_form4_parsed == False)  # noqa: E712

    return db.scalars(stmt).all()


def _mark_failed(
    db: Session,
    *,
    filing: Filing,
    error: str,
) -> None:
    filing.processing_status = "failed"
    filing.last_error_message = error

    log_event(
        db,
        event_type="failed",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "form4_pipeline",
            "error": error,
        },
    )


def _looks_like_ownership_xml(text: str) -> bool:
    sample = text.lstrip()[:500].lower()
    return sample.startswith("<?xml") or "<ownershipdocument" in sample


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Form 4 end-to-end pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticker", help="Ticker symbol, e.g. AAPL")
    source.add_argument("--cik", help="SEC CIK, e.g. 0001731289")
    parser.add_argument("--max", type=int, default=20, help="Max Form 4 filings to ingest")
    parser.add_argument("--parse-limit", type=int, default=20, help="Max stored Form 4 filings to parse")
    parser.add_argument("--skip-ingest", action="store_true", help="Only parse stored Form 4 filings")
    parser.add_argument("--force-parse", action="store_true", help="Parse already parsed Form 4 filings again")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not check_connection():
        raise SystemExit("Cannot connect to PostgreSQL. Check your .env / Docker setup.")

    result = asyncio.run(
        run_form4_pipeline(
            ticker=args.ticker,
            cik=args.cik,
            max_filings=args.max,
            parse_limit=args.parse_limit,
            skip_ingest=args.skip_ingest,
            force_parse=args.force_parse,
        )
    )

    ingest = result.get("ingest") or {}
    parse = result["parse"]

    if ingest:
        print("\nIngest")
        print(f"  Ingested: {ingest.get('ingested', 0)}")
        print(f"  Skipped:  {ingest.get('skipped', 0)}")
        print(f"  Failed:   {ingest.get('failed', 0)}")

    print("\nParse")
    print(f"  Selected:            {parse['selected']}")
    print(f"  Processed:           {parse['processed']}")
    print(f"  Failed:              {parse['failed']}")
    print(f"  Repaired raw files:  {parse['repaired_raw_files']}")
    print(f"  Stored transactions: {parse['stored_transactions']}")


if __name__ == "__main__":
    main()
