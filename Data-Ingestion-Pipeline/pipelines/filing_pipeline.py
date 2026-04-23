"""
filing_pipeline.py

End-to-end pipeline for 10-K and 10-Q filings. This pipeline can ingest recent
filings for one company, extract text sections, parse XBRL facts, generate
embeddings, and run the full signal stack in filing order.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.session import check_connection, get_db
from pipelines.ingestion_pipeline import ingest_company
from processing.embeddings import embed_filing
from processing.filing_splitter import split_filing
from processing.xbrl_parser import parse_company_xbrl_facts
from pipelines.signals_pipeline import run_all_signals

logger = logging.getLogger("pipelines.filing_pipeline")
SUPPORTED_FILING_PIPELINE_FORMS = {"10-K", "10-Q"}


async def run_filing_pipeline(
    *,
    ticker: str | None = None,
    cik: str | None = None,
    form_type: str = "10-K",
    max_filings: int = 5,
    start: date | None = None,
    end: date | None = None,
    skip_ingest: bool = False,
    force_xbrl: bool = False,
    force_embed: bool = False,
    skip_signals: bool = False,
) -> dict[str, Any]:
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    normalized_form = form_type.upper().strip()
    if normalized_form not in SUPPORTED_FILING_PIPELINE_FORMS:
        raise ValueError(
            f"filing_pipeline only supports {sorted(SUPPORTED_FILING_PIPELINE_FORMS)}, "
            f"got {form_type!r}"
        )

    normalized_ticker = ticker.upper().strip() if ticker else None
    normalized_cik = str(cik).strip().zfill(10) if cik else None

    ingest_summary: dict[str, Any] | None = None
    if not skip_ingest:
        ingest_summary = await ingest_company(
            ticker=normalized_ticker,
            cik=normalized_cik,
            form_type=normalized_form,
            max_filings=max_filings,
            start=start,
            end=end,
        )

    with get_db() as db:
        try:
            company = _resolve_company(db, ticker=normalized_ticker, cik=normalized_cik)
        except RuntimeError as exc:
            if ingest_summary and ingest_summary.get("error"):
                raise RuntimeError(
                    "Filing pipeline bootstrap failed before the company could be stored. "
                    f"{ingest_summary['error']}"
                ) from exc
            raise
        filings = _load_target_filings(
            db,
            company_id=company.id,
            form_type=normalized_form,
            limit=max_filings,
        )

        summary: dict[str, Any] = {
            "ticker": company.ticker,
            "cik": company.cik,
            "form_type": normalized_form,
            "ingest": ingest_summary,
            "selected": len(filings),
            "processed": 0,
            "failed": 0,
            "results": [],
        }

        for filing in filings:
            try:
                split_result = split_filing(filing.id, db=db)
                xbrl_result = parse_company_xbrl_facts(
                    filing_id=filing.id,
                    db=db,
                    force=force_xbrl,
                )
                embedding_result = embed_filing(
                    filing.id,
                    db=db,
                    force=force_embed,
                )

                signal_result: dict[str, Any] | None = None
                if not skip_signals:
                    signal_result = run_all_signals(filing.id, db=db)

                summary["processed"] += 1
                summary["results"].append(
                    {
                        "filing_id": filing.id,
                        "accession_number": filing.accession_number,
                        "filed_at": filing.filed_at.isoformat(),
                        "processing_status": filing.processing_status,
                        "split": {
                            "section_count": len(split_result.sections),
                            "warnings": split_result.warnings,
                        },
                        "xbrl": xbrl_result.to_dict(),
                        "embeddings": {
                            "stored_count": embedding_result.stored_count,
                            "warnings": embedding_result.warnings,
                        },
                        "signals": signal_result,
                    }
                )
            except Exception as exc:
                logger.error(
                    "Failed filing pipeline for filing %d (%s): %s",
                    filing.id,
                    filing.accession_number,
                    exc,
                )
                summary["failed"] += 1

        return summary


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
        company = db.scalar(select(Company).where(Company.cik == cik))

    if company is None:
        identifier = ticker or cik or "unknown"
        raise RuntimeError(f"Company {identifier!r} not found in database")

    return company


def _load_target_filings(
    db: Session,
    *,
    company_id: int,
    form_type: str,
    limit: int,
) -> list[Filing]:
    filings = db.scalars(
        select(Filing)
        .where(
            Filing.company_id == company_id,
            Filing.form_type == form_type,
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(filings))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the 10-K / 10-Q end-to-end filing pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticker", help="Ticker symbol, e.g. AAPL")
    source.add_argument("--cik", help="SEC CIK, e.g. 0001731289")
    parser.add_argument("--form", default="10-K", help="Form type: 10-K or 10-Q")
    parser.add_argument("--max", type=int, default=5, help="Max filings to ingest/process")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--skip-ingest", action="store_true", help="Only process already stored filings")
    parser.add_argument("--force-xbrl", action="store_true", help="Reparse XBRL facts")
    parser.add_argument("--force-embed", action="store_true", help="Recompute embeddings")
    parser.add_argument("--skip-signals", action="store_true", help="Stop after embeddings")
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

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    result = asyncio.run(
        run_filing_pipeline(
            ticker=args.ticker,
            cik=args.cik,
            form_type=args.form,
            max_filings=args.max,
            start=start,
            end=end,
            skip_ingest=args.skip_ingest,
            force_xbrl=args.force_xbrl,
            force_embed=args.force_embed,
            skip_signals=args.skip_signals,
        )
    )

    print("\nPipeline")
    print(f"  Ticker:    {result['ticker']}")
    print(f"  CIK:       {result['cik']}")
    print(f"  Form:      {result['form_type']}")
    print(f"  Selected:  {result['selected']}")
    print(f"  Processed: {result['processed']}")
    print(f"  Failed:    {result['failed']}")


if __name__ == "__main__":
    main()
