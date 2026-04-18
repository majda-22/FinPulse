"""
text_pipeline.py

End-to-end pipeline for filing narrative text. This pipeline extracts filing
sections, generates embeddings, and computes text drift signals for one 10-K
or 10-Q filing.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.session import check_connection, get_db
from processing.embeddings import embed_filing
from processing.filing_splitter import split_filing
from signals.section_signals import compute_and_store_section_signals

logger = logging.getLogger("pipelines.text_pipeline")


def run_text_pipeline(
    filing_id: int,
    *,
    db: Session | None = None,
    force_embed: bool = False,
) -> dict[str, Any]:
    if db is None:
        with get_db() as session:
            return run_text_pipeline(
                filing_id,
                db=session,
                force_embed=force_embed,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")
    if filing.form_type not in {"10-K", "10-Q"}:
        raise RuntimeError(
            f"text_pipeline should target a 10-K or 10-Q, got {filing.form_type!r}"
        )

    split_result = split_filing(filing_id, db=db)
    embedding_result = embed_filing(filing_id, db=db, force=force_embed)
    signals = compute_and_store_section_signals(filing_id, db=db)

    return {
        "filing_id": filing.id,
        "accession_number": filing.accession_number,
        "form_type": filing.form_type,
        "processing_status": filing.processing_status,
        "split": {
            "section_count": len(split_result.sections),
            "sections": [section.section for section in split_result.sections],
            "warnings": split_result.warnings,
        },
        "embeddings": {
            "stored_count": embedding_result.stored_count,
            "chunk_count": embedding_result.chunk_count,
            "warnings": embedding_result.warnings,
            "provider": embedding_result.provider,
            "model": embedding_result.model,
        },
        "signals": {
            "count": len(signals),
            "signal_names": [signal["signal_name"] for signal in signals],
            "not_available": [
                signal["signal_name"]
                for signal in signals
                if signal.get("signal_value") is None
            ],
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the filing text pipeline for one filing")
    parser.add_argument("--filing-id", type=int, required=True, help="Database filing id")
    parser.add_argument("--force-embed", action="store_true", help="Recompute embeddings")
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

    result = run_text_pipeline(
        args.filing_id,
        force_embed=args.force_embed,
    )
    print(result)


if __name__ == "__main__":
    main()

