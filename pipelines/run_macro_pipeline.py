"""
run_macro_pipeline.py

End-to-end pipeline for macroeconomic observations. This pipeline fetches a
small default set of FRED series, stores their observations, and logs a
pipeline event with the ingest summary.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import date
from typing import Any

from app.db.session import check_connection, get_db
from ingestion.company_repo import log_event
from ingestion.fred_client import DEFAULT_FRED_PROVIDER, FredClient
from ingestion.macro_repo import upsert_macro_observations

logger = logging.getLogger("pipelines.run_macro_pipeline")

DEFAULT_MACRO_SERIES: tuple[str, ...] = (
    "CPIAUCSL",  # CPI
    "FEDFUNDS",  # Fed funds rate
    "DGS10",     # 10Y Treasury yield
    "UNRATE",    # Unemployment rate
    "INDPRO",    # Industrial production
    "VIXCLS",    # VIX
    "BAA10Y",    # Baa-Treasury credit spread proxy
)


async def run_macro_pipeline(
    *,
    series_ids: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    provider: str = DEFAULT_FRED_PROVIDER,
) -> dict[str, Any]:
    selected_series = series_ids or list(DEFAULT_MACRO_SERIES)
    selected_series = [series_id.strip().upper() for series_id in selected_series if series_id.strip()]
    if not selected_series:
        raise ValueError("Provide at least one macro series id")

    t0 = time.monotonic()
    fetched_rows = 0
    inserted = 0
    updated = 0
    deduped_in_batch = 0
    series_summaries: list[dict[str, Any]] = []

    try:
        async with FredClient() as client:
            with get_db() as db:
                for series_id in selected_series:
                    rows = await client.fetch_series_observations(
                        series_id=series_id,
                        start=start,
                        end=end,
                        provider=provider,
                    )
                    write_summary = upsert_macro_observations(db, rows=rows)

                    fetched_rows += len(rows)
                    inserted += write_summary["inserted"]
                    updated += write_summary["updated"]
                    deduped_in_batch += write_summary["deduped_in_batch"]

                    series_summaries.append(
                        {
                            "series_id": series_id,
                            "fetched": len(rows),
                            "inserted": write_summary["inserted"],
                            "updated": write_summary["updated"],
                        }
                    )

                duration_ms = int((time.monotonic() - t0) * 1000)
                log_event(
                    db,
                    event_type="macro_observations_ingested",
                    layer="polling",
                    duration_ms=duration_ms,
                    detail={
                        "step": "run_macro_pipeline",
                        "provider": provider,
                        "series_ids": selected_series,
                        "start": start.isoformat() if start else None,
                        "end": end.isoformat() if end else None,
                        "fetched": fetched_rows,
                        "inserted": inserted,
                        "updated": updated,
                        "deduped_in_batch": deduped_in_batch,
                    },
                )
        return {
            "provider": provider,
            "series_ids": selected_series,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "fetched": fetched_rows,
            "inserted": inserted,
            "updated": updated,
            "deduped_in_batch": deduped_in_batch,
            "stored": inserted + updated,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "series": series_summaries,
        }
    except Exception as exc:
        with get_db() as db:
            log_event(
                db,
                event_type="failed",
                layer="polling",
                detail={
                    "step": "run_macro_pipeline",
                    "provider": provider,
                    "series_ids": selected_series,
                    "start": start.isoformat() if start else None,
                    "end": end.isoformat() if end else None,
                    "error": str(exc),
                },
            )
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the macro observations pipeline")
    parser.add_argument(
        "--series",
        nargs="+",
        help="Optional FRED series ids. Defaults to a small core macro set.",
    )
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument(
        "--provider",
        default=DEFAULT_FRED_PROVIDER,
        help=f"Provider label (default: {DEFAULT_FRED_PROVIDER})",
    )
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
        run_macro_pipeline(
            series_ids=args.series,
            start=start,
            end=end,
            provider=args.provider,
        )
    )

    print("\nMacro Observations")
    print(f"  Provider:          {result['provider']}")
    print(f"  Series count:      {len(result['series_ids'])}")
    print(f"  Fetched:           {result['fetched']}")
    print(f"  Inserted:          {result['inserted']}")
    print(f"  Updated:           {result['updated']}")
    print(f"  Deduped in batch:  {result['deduped_in_batch']}")
    print(f"  Stored:            {result['stored']}")


if __name__ == "__main__":
    main()
