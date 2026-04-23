"""
xbrl_pipeline.py

End-to-end pipeline for filing XBRL data. This pipeline parses XBRL facts for
one filing and computes numeric XBRL signals when the filing type supports
numeric scoring.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.session import check_connection, get_db
from processing.xbrl_parser import SUPPORTED_XBRL_FORMS, parse_company_xbrl_facts
from signals.xbrl_signals import compute_and_store_xbrl_signals

logger = logging.getLogger("pipelines.xbrl_pipeline")


def run_xbrl_pipeline(
    filing_id: int,
    *,
    db: Session | None = None,
    force_parse: bool = False,
    skip_signals: bool = False,
) -> dict[str, Any]:
    if db is None:
        with get_db() as session:
            return run_xbrl_pipeline(
                filing_id,
                db=session,
                force_parse=force_parse,
                skip_signals=skip_signals,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")
    if filing.form_type not in SUPPORTED_XBRL_FORMS:
        raise RuntimeError(
            f"xbrl_pipeline does not support filing form {filing.form_type!r}"
        )

    parse_result = parse_company_xbrl_facts(
        filing_id=filing_id,
        db=db,
        force=force_parse,
    )

    signals: list[dict[str, Any]] = []
    skipped_signal_reason: str | None = None
    if skip_signals:
        skipped_signal_reason = "signals_skipped_by_request"
    elif filing.form_type in {"10-K", "10-Q"}:
        signals = compute_and_store_xbrl_signals(filing_id, db=db)
    else:
        skipped_signal_reason = f"numeric_signals_not_supported_for_{filing.form_type}"

    return {
        "filing_id": filing.id,
        "accession_number": filing.accession_number,
        "form_type": filing.form_type,
        "processing_status": filing.processing_status,
        "xbrl_parse": parse_result.to_dict(),
        "signals": {
            "count": len(signals),
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"]
                for signal in signals
                if signal.get("signal_value") is None
            ],
            "skipped_reason": skipped_signal_reason,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the XBRL pipeline for one filing")
    parser.add_argument("--filing-id", type=int, required=True, help="Database filing id")
    parser.add_argument("--force-parse", action="store_true", help="Reparse XBRL facts")
    parser.add_argument("--skip-signals", action="store_true", help="Only parse XBRL facts")
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

    result = run_xbrl_pipeline(
        args.filing_id,
        force_parse=args.force_parse,
        skip_signals=args.skip_signals,
    )
    print(result)


if __name__ == "__main__":
    main()

