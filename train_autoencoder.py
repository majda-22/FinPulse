#!/usr/bin/env python3
"""
PHASE 2: Entraîner les autoencoders par secteur

Script pour entraîner les autoencoders sur les embeddings existants.

Utilisation:
    python train_autoencoder.py                          # Tous les secteurs
    python train_autoencoder.py --sector 7372            # Secteur spécifique
    python train_autoencoder.py --sector 7372 3721       # Multiple secteurs
"""

import argparse
import sys
from datetime import datetime
import logging

# Ajouter le chemin racine
sys.path.insert(0, "/".join(__file__.split("/")[:-1]))

from app.db.session import SessionLocal
from signals.sector_autoencoder import train_autoencoders_for_all_sectors

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Fonction principale."""
    
    parser = argparse.ArgumentParser(
        description="Entraîner les autoencoders pour les filings financiers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Tous les secteurs
  python train_autoencoder.py
  
  # Secteur 3721 (Semiconductors)
  python train_autoencoder.py --sector 3721
  
  # Multiple secteurs
  python train_autoencoder.py --sector 7372 3721 2731
  
  # Avec verbosité
  python train_autoencoder.py --verbose
        """
    )
    
    parser.add_argument(
        "--sector",
        type=str,
        nargs="*",
        default=None,
        help="SIC code(s) à traiter (ex: 7372, 3721). Si absent, tous les secteurs."
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Augmente la verbosité"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    if args.verbose:
        logging.getLogger("sector_autoencoder").setLevel(logging.DEBUG)
    
    logger.info("=" * 70)
    logger.info("PHASE 2: ENTRAÎNEMENT DES AUTOENCODERS")
    logger.info("=" * 70)
    logger.info(f"Heure de démarrage: {datetime.now().isoformat()}")
    
    # Créer la session
    session = SessionLocal()
    
    try:
        # Convertir les arguments en liste
        sector_codes = args.sector if args.sector else None
        
        if sector_codes:
            logger.info(f"Secteurs à traiter: {', '.join(sector_codes)}")
        else:
            logger.info("AUTO-DETECTION: Tous les secteurs avec embeddings...")
        
        # Lancer l'entraînement
        logger.info("-" * 70)
        trained = train_autoencoders_for_all_sectors(session, sector_codes=sector_codes)
        logger.info("-" * 70)
        
        if trained:
            logger.info(f"✅ SUCCÈS: {len(trained)} secteurs entraînés")
            logger.info(f"Secteurs: {', '.join(trained)}")
        else:
            logger.warning("⚠️  Aucun secteur n'a pu être entraîné")
            sys.exit(1)
        
        logger.info(f"Heure de fin: {datetime.now().isoformat()}")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"❌ ERREUR: {e}", exc_info=True)
        sys.exit(1)
    
    finally:
        session.close()


if __name__ == "__main__":
    main()
