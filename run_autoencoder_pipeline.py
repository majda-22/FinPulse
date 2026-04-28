"""
run_autoencoder_pipeline.py

ÉTAPE 1 du pipeline avancé : scorer les embeddings d'un filing
avec les autoencoders sectoriels avant le calcul des signals.

Usage:
    python run_autoencoder_pipeline.py --filing-id 123
    python run_autoencoder_pipeline.py --filing-id 123 --dry-run
"""

import argparse
import logging
from typing import Any

from app.db.session import get_db
from signals.sector_autoencoder import compute_embeddings_anomaly_scores

logger = logging.getLogger(__name__)


def run_autoencoder_pipeline(filing_id: int, *, dry_run: bool = False) -> dict[str, Any]:
    with get_db() as db:
        try:
            compute_embeddings_anomaly_scores(db, filing_id, commit=not dry_run)
            status = "dry_run" if dry_run else "scored"
            logger.info("Autoencoder scoring complete for filing %d (status=%s)", filing_id, status)
            return {"filing_id": filing_id, "status": status}
        except Exception as exc:
            logger.warning("Autoencoder scoring skipped for filing %d: %s", filing_id, exc)
            return {"filing_id": filing_id, "status": "skipped", "reason": str(exc)}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score embeddings for a filing using sector autoencoders (ÉTAPE 1)"
    )
    parser.add_argument("--filing-id", type=int, required=True, help="Database filing id")
    parser.add_argument("--dry-run", action="store_true", help="Compute scores without committing")
    return parser.parse_args()


def main() -> dict[str, Any]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args()
    result = run_autoencoder_pipeline(args.filing_id, dry_run=args.dry_run)
    print(result)
    return result


if __name__ == "__main__":
    main()
