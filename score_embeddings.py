#!/usr/bin/env python3
"""
PHASE 3: Scorer les embeddings avec les autoencoders

Script pour calculer les anomaly_scores pour les embeddings existants.

Utilisation:
    python score_embeddings.py                           # Tous les filings non-scorés
    python score_embeddings.py --filing 12345            # Filing spécifique
    python score_embeddings.py --filing 12345 12346 12347  # Multiple filings
    python score_embeddings.py --company 1234            # Tous les filings d'une company
    python score_embeddings.py --recent 10               # 10 derniers filings
    python score_embeddings.py --batch 50                # Process 50 filings par batch
"""
import argparse
import sys
from datetime import datetime
import logging

# Ajouter le chemin racine
sys.path.insert(0, "/".join(__file__.split("/")[:-1]))

from app.db.session import SessionLocal
from app.db.models import Filing, Embedding
from signals.sector_autoencoder import (
    compute_embeddings_anomaly_scores,
    compute_anomaly_scores_batch
)

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_filings_to_process(session, args):
    """
    Déterminer quels filings traiter basé sur les arguments.
    
    Returns:
        List[int] d'IDs de filings
    """
    query = session.query(Filing.id)
    
    if args.filing:
        # Filing(s) spécifique(s)
        filing_ids = [int(f) for f in args.filing]
        query = query.filter(Filing.id.in_(filing_ids))
        logger.info(f"Filtré: {len(filing_ids)} filings spécifiques")
    
    elif args.company:
        # Tous les filings d'une company
        company_id = int(args.company)
        query = query.filter(Filing.company_id == company_id)
        logger.info(f"Filtré: Tous les filings de company_id={company_id}")
    
    elif args.recent:
        # N derniers filings
        n = int(args.recent)
        query = query.order_by(Filing.created_at.desc()).limit(n)
        logger.info(f"Filtré: {n} derniers filings")
    
    else:
        # Tous les filings non-scorés
        query = query.filter(Filing.is_anomaly_scored == False)
        logger.info("Filtré: Tous les filings non-scorés (is_anomaly_scored=False)")
    
    result = [row[0] for row in query.all()]
    logger.info(f"Total filings à traiter: {len(result)}")
    
    return result


def main():
    """Fonction principale."""
    
    parser = argparse.ArgumentParser(
        description="Scorer les embeddings avec les autoencoders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Tous les filings non-scorés
  python score_embeddings.py
  
  # Filing spécifique
  python score_embeddings.py --filing 12345
  
  # Multiple filings
  python score_embeddings.py --filing 12345 12346 12347
  
  # Tous les filings d'une company
  python score_embeddings.py --company 1234
  
  # 10 derniers filings
  python score_embeddings.py --recent 10
  
  # Batch process avec 50 filings par batch
  python score_embeddings.py --batch 50
  
  # Verbose mode
  python score_embeddings.py --verbose
        """
    )
    
    parser.add_argument(
        "--filing",
        type=str,
        nargs="*",
        default=None,
        help="Filing ID(s) à traiter"
    )
    
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Company ID: tous les filings de cette company"
    )
    
    parser.add_argument(
        "--recent",
        type=str,
        default=None,
        help="N derniers filings (ex: 10)"
    )
    
    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        help="Filings par batch (défaut: 1, pas de batch)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Augmente la verbosité"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ne pas commiter les changements, afficher seulement"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    if args.verbose:
        logging.getLogger("sector_autoencoder").setLevel(logging.DEBUG)
    
    logger.info("=" * 70)
    logger.info("PHASE 3: SCORING DES EMBEDDINGS")
    logger.info("=" * 70)
    logger.info(f"Heure de démarrage: {datetime.now().isoformat()}")
    if args.dry_run:
        logger.warning("⚠️  MODE DRY-RUN: Les changements ne seront pas committés")
    
    # Créer la session
    session = SessionLocal()
    
    try:
        # Déterminer les filings à traiter
        logger.info("-" * 70)
        filing_ids = get_filings_to_process(session, args)
        logger.info("-" * 70)
        
        if not filing_ids:
            logger.warning("⚠️  Aucun filing à traiter")
            sys.exit(0)
        
        # Traiter
        logger.info("-" * 70)
        if args.batch > 1:
            logger.info(f"Processing en mode BATCH: {args.batch} filings/batch")
            compute_anomaly_scores_batch(
                session,
                filing_ids,
                batch_size=args.batch
            )
        else:
            logger.info("Processing en mode SÉQUENTIEL")
            for i, filing_id in enumerate(filing_ids, 1):
                logger.info(f"[{i}/{len(filing_ids)}] Processing filing {filing_id}...")
                try:
                    compute_embeddings_anomaly_scores(
                        session,
                        filing_id,
                        commit=(not args.dry_run)
                    )
                except Exception as e:
                    logger.error(f"  ❌ Erreur: {e}")
        
        logger.info("-" * 70)
        
        if args.dry_run:
            logger.info("✅ DRY-RUN COMPLET: Aucune données modifiées")
        else:
            logger.info(f"✅ SUCCÈS: {len(filing_ids)} filings scorés")
        
        # Stats finales
        logger.info("-" * 70)
        scored_embeddings = session.query(Embedding).filter(
            Embedding.anomaly_score.isnot(None)
        ).count()
        logger.info(f"Total embeddings avec anomaly_score: {scored_embeddings}")
        
        # Distribution
        from sqlalchemy import func
        stats = session.query(
            func.min(Embedding.anomaly_score).label("min"),
            func.max(Embedding.anomaly_score).label("max"),
            func.avg(Embedding.anomaly_score).label("avg"),
        ).filter(
            Embedding.anomaly_score.isnot(None)
        ).first()
        
        if stats.min is not None:
            logger.info(f"Anomaly Score Distribution:")
            logger.info(f"  Min: {stats.min:.4f}")
            logger.info(f"  Max: {stats.max:.4f}")
            logger.info(f"  Avg: {stats.avg:.4f}")
        
        logger.info(f"Heure de fin: {datetime.now().isoformat()}")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"❌ ERREUR: {e}", exc_info=True)
        sys.exit(1)
    
    finally:
        session.close()


if __name__ == "__main__":
    main()
