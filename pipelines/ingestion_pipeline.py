"""
ingestion_pipeline.py

End-to-end ingestion pipeline for raw SEC filings. This pipeline fetches
company metadata, downloads filing content, stores the raw documents, and
inserts filing rows in the database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import date
from typing import Optional

from app.db.session import check_connection, get_db
from ingestion.company_repo import insert_filing, log_event, upsert_company
from ingestion.edgar_client import EdgarClient, FilingMeta
from ingestion.file_store import FileStore
from ingestion.form4_client import FORM4_FORMS, Form4Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipelines.ingestion_pipeline")


async def ingest_company(
    *,
    ticker: Optional[str] = None,
    cik: Optional[str] = None,
    form_type: str = "10-K",
    max_filings: int = 10,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict:
    """
    End-to-end ingestion for one company identified by ticker or CIK.
    """
    if bool(ticker) == bool(cik):
        raise ValueError("Provide exactly one of ticker or cik")

    ticker_normalized = ticker.upper().strip() if ticker else None
    cik_normalized = str(cik).strip().zfill(10) if cik else None
    company_ref = ticker_normalized or cik_normalized or "UNKNOWN"

    t_start = time.monotonic()
    store = FileStore()
    summary = {
        "ticker": ticker_normalized,
        "cik": cik_normalized,
        "identifier": company_ref,
        "form_type": form_type,
        "ingested": 0,
        "skipped": 0,
        "failed": 0,
        "error": None,
    }

    logger.info("=" * 60)
    logger.info("Starting ingestion: %s  form=%s  max=%d", company_ref, form_type, max_filings)
    logger.info("=" * 60)

    async with EdgarClient() as client:
        try:
            if cik_normalized:
                company_meta = await client.get_company_meta_by_cik(cik_normalized)
            else:
                company_meta = await client.get_company_meta(ticker_normalized)
            summary["ticker"] = company_meta.ticker
            summary["cik"] = company_meta.cik
            summary["identifier"] = company_meta.ticker or company_meta.cik
            logger.info(
                "Company: %s  CIK=%s  SIC=%s",
                company_meta.name,
                company_meta.cik,
                company_meta.sic_code,
            )
        except Exception as exc:
            error_message = f"Failed to fetch company meta for {company_ref}: {exc}"
            logger.error(error_message)
            summary["failed"] += 1
            summary["error"] = error_message
            return summary

        with get_db() as db:
            company = upsert_company(db, company_meta)
            company_id = company.id

            log_event(
                db,
                event_type="ingested",
                layer="bootstrap",
                company_id=company_id,
                detail={
                    "step": "company_upsert",
                    "ticker": company_meta.ticker,
                    "cik": company_meta.cik,
                },
            )

        try:
            if cik_normalized:
                filings = await client.get_recent_filings_by_cik(
                    cik=company_meta.cik,
                    forms={form_type},
                    limit=max_filings,
                )
            else:
                filings = await client.get_recent_filings(
                    ticker=company_meta.ticker,
                    forms={form_type},
                    limit=max_filings,
                )
        except Exception as exc:
            error_message = f"Failed to fetch filings for {company_ref}: {exc}"
            logger.error(error_message)
            with get_db() as db:
                log_event(
                    db,
                    event_type="failed",
                    layer="bootstrap",
                    company_id=company_id,
                    detail={
                        "step": "fetch_recent_filings",
                        "ticker": company_meta.ticker,
                        "cik": company_meta.cik,
                        "form_type": form_type,
                        "error": str(exc),
                    },
                )
            summary["failed"] += 1
            summary["error"] = error_message
            return summary

        logger.info("Found %d filings for %s", len(filings), summary["identifier"])

        for meta in filings:
            await _ingest_one_filing(client, store, meta, company_id, summary)

    elapsed = time.monotonic() - t_start
    logger.info(
        "Done: %s — ingested=%d  skipped=%d  failed=%d  (%.1fs)",
        summary["identifier"],
        summary["ingested"],
        summary["skipped"],
        summary["failed"],
        elapsed,
    )
    return summary


async def ingest_ticker(
    ticker: str,
    form_type: str = "10-K",
    max_filings: int = 10,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict:
    return await ingest_company(
        ticker=ticker,
        form_type=form_type,
        max_filings=max_filings,
        start=start,
        end=end,
    )


async def _ingest_one_filing(
    client: EdgarClient,
    store: FileStore,
    meta: FilingMeta,
    company_id: int,
    summary: dict,
) -> None:
    t0 = time.monotonic()

    logger.info(
        "  Filing: %s  %s  filed=%s",
        meta.form_type,
        meta.accession_number,
        meta.filed_at,
    )

    s3_key = store._make_key(meta.cik, meta.accession_number, meta.form_type)

    if store.exists(s3_key):
        logger.info("    Already stored — skipping download")

        with get_db() as db:
            filing, created = insert_filing(db, company_id, meta, s3_key)

            log_event(
                db,
                event_type="skipped",
                layer="bootstrap",
                company_id=company_id,
                filing_id=filing.id,
                detail={
                    "reason": "already_stored",
                    "accession": meta.accession_number,
                },
            )

        summary["skipped"] += 1
        return

    try:
        raw_text = await _download_filing_text(client, meta)
    except Exception as exc:
        logger.error("    Download failed: %s", exc)

        with get_db() as db:
            log_event(
                db,
                event_type="failed",
                layer="bootstrap",
                company_id=company_id,
                detail={
                    "step": "download",
                    "accession": meta.accession_number,
                    "error": str(exc),
                },
            )

        summary["failed"] += 1
        return

    try:
        saved_key = store.put(meta.cik, meta.accession_number, meta.form_type, raw_text)
        file_size = store.size_bytes(saved_key)

        logger.info("    Saved to storage: %s  (%d bytes)", saved_key, file_size)
    except Exception as exc:
        logger.error("    Storage write failed: %s", exc)

        with get_db() as db:
            log_event(
                db,
                event_type="failed",
                layer="bootstrap",
                company_id=company_id,
                detail={
                    "step": "storage_write",
                    "accession": meta.accession_number,
                    "error": str(exc),
                },
            )

        summary["failed"] += 1
        return

    duration_ms = int((time.monotonic() - t0) * 1000)

    with get_db() as db:
        filing, created = insert_filing(db, company_id, meta, saved_key, file_size)

        log_event(
            db,
            event_type="ingested",
            layer="bootstrap",
            company_id=company_id,
            filing_id=filing.id,
            duration_ms=duration_ms,
            detail={
                "accession": meta.accession_number,
                "form_type": meta.form_type,
                "filed_at": str(meta.filed_at),
                "file_bytes": file_size,
                "storage_key": saved_key,
            },
        )

    summary["ingested"] += 1


async def _download_filing_text(client: EdgarClient, meta: FilingMeta) -> str:
    if meta.form_type in FORM4_FORMS:
        return await Form4Client(client).get_form4_xml(
            accession_number=meta.accession_number,
            cik=meta.cik,
            primary_document=meta.primary_document,
        )

    return await client.get_filing_text(meta)


async def ingest_batch(
    tickers: list[str],
    form_type: str = "10-K",
    max_filings: int = 10,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> list[dict]:
    results = []
    for ticker in tickers:
        result = await ingest_ticker(
            ticker=ticker,
            form_type=form_type,
            max_filings=max_filings,
            start=start,
            end=end,
        )
        results.append(result)
    return results


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the raw filing ingestion pipeline")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ticker", nargs="+", help="One or more tickers, e.g. AAPL MSFT")
    source.add_argument("--cik", help="SEC CIK, e.g. 0001731289")
    parser.add_argument("--form", default="10-K", help="Form type (default: 10-K)")
    parser.add_argument("--max", type=int, default=5, help="Max filings per ticker (default: 5)")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    return parser.parse_args()


def main():
    args = _parse_args()

    if not check_connection():
        logger.error("Cannot connect to PostgreSQL. Check your .env / Docker setup.")
        raise SystemExit(1)

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    if args.cik:
        results = [
            asyncio.run(
                ingest_company(
                    cik=args.cik,
                    form_type=args.form,
                    max_filings=args.max,
                    start=start,
                    end=end,
                )
            )
        ]
    else:
        results = asyncio.run(
            ingest_batch(
                tickers=[ticker.upper() for ticker in args.ticker],
                form_type=args.form,
                max_filings=args.max,
                start=start,
                end=end,
            )
        )

    print("\n" + "=" * 50)
    print(f"{'Company':<16} {'Ingested':>10} {'Skipped':>10} {'Failed':>10}")
    print("-" * 50)
    for result in results:
        company_label = (
            result.get("ticker")
            or result.get("cik")
            or result.get("identifier")
            or "UNKNOWN"
        )
        print(
            f"{company_label:<16} "
            f"{result['ingested']:>10} "
            f"{result['skipped']:>10} "
            f"{result['failed']:>10}"
        )
    print("=" * 50)


if __name__ == "__main__":
    main()
