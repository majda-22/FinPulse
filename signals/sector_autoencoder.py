"""
Sector Autoencoder: Détecteur d'anomalies pour les embeddings de filings financiers

Ce module implémente un autoencoder par secteur industriel pour:
1. Apprendre la "structure normale" des embeddings d'un secteur
2. Détecter les paragraphes anomalous lors de la reconstruction
3. Scorer les anomalies sur une échelle [0, 1]

Architecture:
    Input (1024 dims) 
    ↓
    Encoder: 1024 → 512 → 256 (compression)
    ↓
    Decoder: 256 → 512 → 1024 (reconstruction)
    ↓
    Loss = MSE(input, output) → normalized to anomaly_score
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from datetime import datetime, timedelta
import pickle
import os
from pathlib import Path
from typing import Dict, Tuple, Optional, List
import logging
from contextlib import contextmanager

# Logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ============================================================================
# HYPERPARAMÈTRES GLOBAUX
# ============================================================================

# Architecture
EMBEDDING_DIM = 1024                          # Dimension des embeddings Mistral
AUTOENCODER_HIDDEN_SIZE = 512                 # Couche cachée 1
AUTOENCODER_BOTTLENECK_SIZE = 256             # Goulot d'étranglement

# Entraînement
AUTOENCODER_LEARNING_RATE = 0.001
AUTOENCODER_EPOCHS = 50
AUTOENCODER_BATCH_SIZE = 32
AUTOENCODER_WEIGHT_DECAY = 1e-5               # Régularisation L2

# Seuils et normalisation
AUTOENCODER_ANOMALY_THRESHOLD_PERCENTILE = 95  # Top 5% = anomalies
MIN_SAMPLES_FOR_TRAINING = 100                 # Minimum embeddings par secteur
BACKFILL_DAYS = 365                            # Données des 12 derniers mois

# Stockage des modèles
MODELS_DIR = Path("data/autoencoder_models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# 1. CLASSE AUTOENCODER
# ============================================================================

class VectorAutoencoder(nn.Module):
    """
    Autoencoder symétrique pour détecter les anomalies dans les embeddings.
    
    Architecture:
    - Encodeur: 1024 → 512 → 256 (compresse les informations)
    - Décodeur: 256 → 512 → 1024 (reconstruit à partir de la forme comprimée)
    
    Logique: Un embedding "normal" peut être bien reconstruit.
    Un embedding "anormal" sera mal reconstruit → MSE élevé.
    """
    
    def __init__(
        self,
        input_dim: int = EMBEDDING_DIM,
        hidden_size: int = AUTOENCODER_HIDDEN_SIZE,
        bottleneck_size: int = AUTOENCODER_BOTTLENECK_SIZE
    ):
        super().__init__()
        
        # Encodeur: Compresse l'embedding original
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_size),
            nn.ReLU(),
            nn.Dropout(0.1),  # Prévient l'overfitting
            nn.Linear(hidden_size, bottleneck_size),
            nn.ReLU(),
        )
        
        # Décodeur: Reconstruit l'embedding complet
        self.decoder = nn.Sequential(
            nn.Linear(bottleneck_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_size, input_dim),
        )
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass de l'autoencoder.
        
        Args:
            x: Tensor de shape (batch_size, 1024)
            
        Returns:
            Reconstruction de l'input de même shape
        """
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded
    
    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """Retourne uniquement la représentation encodée (bottleneck)."""
        return self.encoder(x)


# ============================================================================
# 2. CLASSE DE GESTION DES MODÈLES
# ============================================================================

class SectorAutoencoderManager:
    """
    Gestionnaire des autoencoders par secteur.
    
    Responsabilités:
    - Entraîner des modèles par secteur
    - Sauvegarder/charger les modèles et leurs seuils
    - Scorer les embeddings
    """
    
    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = models_dir
        self.models = {}  # {sector_code: model}
        self.thresholds = {}  # {sector_code: mse_threshold}
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Using device: {self.device}")
    
    def prepare_sector_dataset(
        self,
        session,
        sector_code: str,
        lookback_days: int = BACKFILL_DAYS
    ) -> Optional[np.ndarray]:
        """
        Charger les embeddings pour un secteur.
        
        Args:
            session: SQLAlchemy session
            sector_code: SIC code (ex: "7372" = Software)
            lookback_days: Récupérer les embeddings des N derniers jours
            
        Returns:
            Array de shape (N, 1024) ou None si insuffisant
        """
        from sqlalchemy import func
        from app.db.models import Embedding, Filing, Company
        
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        # Requête: embeddings du secteur, données récentes
        embeddings_list = session.query(Embedding.embedding).join(
            Filing, Filing.id == Embedding.filing_id
        ).join(
            Company, Company.id == Embedding.company_id
        ).filter(
            Company.sic_code == sector_code,
            Embedding.created_at >= cutoff_date
        ).all()
        
        if not embeddings_list:
            logger.warning(f"Sector {sector_code}: No embeddings found")
            return None
        
        # Convertir de pgvector à numpy
        embeddings_array = np.array([
            np.array(e[0]) for e in embeddings_list
        ])
        
        if len(embeddings_array) < MIN_SAMPLES_FOR_TRAINING:
            logger.warning(
                f"Sector {sector_code}: Only {len(embeddings_array)} samples "
                f"(need {MIN_SAMPLES_FOR_TRAINING}), skipping"
            )
            return None
        
        logger.info(f"Sector {sector_code}: Loaded {len(embeddings_array)} embeddings")
        return embeddings_array
    
    def train_sector_model(
        self,
        sector_code: str,
        train_data: np.ndarray
    ) -> Tuple[VectorAutoencoder, float]:
        """
        Entraîner un autoencoder pour un secteur.
        
        Args:
            sector_code: SIC code
            train_data: Array (N, 1024)
            
        Returns:
            (model, threshold) tuple
        """
        logger.info(f"Training autoencoder for sector {sector_code}...")
        
        # Préparation des données
        split_idx = int(0.8 * len(train_data))
        train_embeddings = train_data[:split_idx]
        val_embeddings = train_data[split_idx:]
        
        train_tensor = torch.FloatTensor(train_embeddings).to(self.device)
        val_tensor = torch.FloatTensor(val_embeddings).to(self.device)
        
        train_dataset = TensorDataset(train_tensor)
        train_loader = DataLoader(
            train_dataset,
            batch_size=AUTOENCODER_BATCH_SIZE,
            shuffle=True
        )
        
        # Modèle, optimiseur, loss
        model = VectorAutoencoder().to(self.device)
        optimizer = optim.Adam(
            model.parameters(),
            lr=AUTOENCODER_LEARNING_RATE,
            weight_decay=AUTOENCODER_WEIGHT_DECAY
        )
        criterion = nn.MSELoss()
        
        # Entraînement
        train_losses = []
        val_losses = []
        
        for epoch in range(AUTOENCODER_EPOCHS):
            # Training phase
            model.train()
            epoch_train_loss = 0.0
            for batch in train_loader:
                x = batch[0]
                output = model(x)
                loss = criterion(output, x)
                
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
                epoch_train_loss += loss.item()
            
            epoch_train_loss /= len(train_loader)
            train_losses.append(epoch_train_loss)
            
            # Validation phase
            model.eval()
            with torch.no_grad():
                val_output = model(val_tensor)
                val_loss = criterion(val_output, val_tensor).item()
                val_losses.append(val_loss)
            
            if (epoch + 1) % 10 == 0:
                logger.info(
                    f"  Epoch {epoch+1}/{AUTOENCODER_EPOCHS}: "
                    f"train_loss={epoch_train_loss:.4f}, "
                    f"val_loss={val_loss:.4f}"
                )
        
        # Calculer le seuil d'anomalie
        model.eval()
        with torch.no_grad():
            train_output = model(train_tensor)
            mse_scores = torch.mean((train_output - train_tensor) ** 2, dim=1)
            mse_numpy = mse_scores.cpu().numpy()
            threshold = float(np.percentile(mse_numpy, AUTOENCODER_ANOMALY_THRESHOLD_PERCENTILE))
        
        logger.info(
            f"Sector {sector_code}: Training complete\n"
            f"  Final train loss: {train_losses[-1]:.4f}\n"
            f"  Final val loss: {val_losses[-1]:.4f}\n"
            f"  Anomaly threshold (95th percentile): {threshold:.4f}"
        )
        
        return model, threshold
    
    def save_model(self, sector_code: str, model: VectorAutoencoder, threshold: float):
        """Sauvegarder le modèle et son seuil."""
        model_path = self.models_dir / f"sector_{sector_code}.pt"
        threshold_path = self.models_dir / f"sector_{sector_code}_threshold.pkl"
        
        torch.save(model.state_dict(), model_path)
        with open(threshold_path, 'wb') as f:
            pickle.dump(threshold, f)
        
        logger.info(f"Model saved: {model_path}")
        logger.info(f"Threshold saved: {threshold_path}")
    
    def load_model(self, sector_code: str) -> Tuple[Optional[VectorAutoencoder], Optional[float]]:
        """Charger le modèle et son seuil pour un secteur."""
        model_path = self.models_dir / f"sector_{sector_code}.pt"
        threshold_path = self.models_dir / f"sector_{sector_code}_threshold.pkl"
        
        if not model_path.exists() or not threshold_path.exists():
            logger.warning(f"Model not found for sector {sector_code}")
            return None, None
        
        model = VectorAutoencoder().to(self.device)
        model.load_state_dict(torch.load(model_path, map_location=self.device))
        model.eval()
        
        with open(threshold_path, 'rb') as f:
            threshold = pickle.load(f)
        
        return model, threshold


# ============================================================================
# 3. FONCTION PUBLIQUE: ENTRAÎNER TOUS LES MODÈLES
# ============================================================================

def train_autoencoders_for_all_sectors(session, sector_codes: Optional[List[str]] = None):
    """
    Entraîner les autoencoders pour tous les secteurs.
    
    Args:
        session: SQLAlchemy session
        sector_codes: List de SIC codes. Si None, détecte automatiquement.
        
    Example:
        >>> from app.db import SessionLocal
        >>> session = SessionLocal()
        >>> train_autoencoders_for_all_sectors(session, sector_codes=["7372", "3721"])
    """
    manager = SectorAutoencoderManager()
    
    # Déterminer les secteurs à traiter
    if sector_codes is None:
        from sqlalchemy import distinct
        from app.db.models import Company
        
        sector_codes = [
            row[0] for row in session.query(distinct(Company.sic_code)).all()
            if row[0]
        ]
        logger.info(f"Found {len(sector_codes)} unique sectors")
    
    # Entraîner pour chaque secteur
    trained_sectors = []
    for sector_code in sector_codes:
        try:
            train_data = manager.prepare_sector_dataset(session, sector_code)
            if train_data is None:
                continue
            
            model, threshold = manager.train_sector_model(sector_code, train_data)
            manager.save_model(sector_code, model, threshold)
            trained_sectors.append(sector_code)
            
        except Exception as e:
            logger.error(f"Error training sector {sector_code}: {e}", exc_info=True)
    
    logger.info(f"✅ Training complete. Trained {len(trained_sectors)} sectors")
    return trained_sectors


# ============================================================================
# 4. FONCTION PUBLIQUE: SCORER LES EMBEDDINGS
# ============================================================================

def compute_embeddings_anomaly_scores(session, filing_id: int, commit: bool = True):
    """
    Calculer les anomaly scores pour tous les embeddings d'un filing.
    
    Processus:
    1. Charger tous les embeddings du filing
    2. Pour chaque embedding, charger le modèle du secteur
    3. Calculer MSE(input, reconstruction)
    4. Normaliser MSE en anomaly_score ∈ [0, 1]
    5. Mettre à jour la BD
    
    Args:
        session: SQLAlchemy session
        filing_id: ID du filing à traiter
        commit: Si True, commite les changements en BD
        
    Example:
        >>> from app.db import SessionLocal
        >>> session = SessionLocal()
        >>> compute_embeddings_anomaly_scores(session, filing_id=12345)
        >>> # BD mise à jour avec reconstruction_error et anomaly_score
    """
    from app.db.models import Embedding, Filing, Company
    
    manager = SectorAutoencoderManager()
    
    # Charger le filing et ses embeddings
    filing = session.query(Filing).get(filing_id)
    if not filing:
        logger.error(f"Filing {filing_id} not found")
        return
    
    embeddings = session.query(Embedding).filter(
        Embedding.filing_id == filing_id
    ).all()
    
    if not embeddings:
        logger.warning(f"No embeddings found for filing {filing_id}")
        return
    
    logger.info(
        f"Processing filing {filing_id} ({filing.company.name}): "
        f"{len(embeddings)} embeddings"
    )
    
    sector_code = filing.company.sic_code
    model, threshold = manager.load_model(sector_code)
    
    if model is None:
        logger.warning(f"No trained model for sector {sector_code}, skipping")
        return
    
    # Calculer les scores
    updated_count = 0
    mse_scores = []
    
    for embedding in embeddings:
        # Convertir en tensor
        embedding_array = np.array(embedding.embedding, dtype=np.float32)
        embedding_tensor = torch.FloatTensor([embedding_array]).to(manager.device)
        
        # Reconstruction
        with torch.no_grad():
            reconstructed = model(embedding_tensor)
            mse = float(torch.mean((embedding_tensor - reconstructed) ** 2).item())
        
        mse_scores.append(mse)
        
        # Normaliser en anomaly_score [0, 1]
        # score = 0 si mse << threshold, score = 1 si mse >> threshold
        if threshold > 0:
            anomaly_score = min(1.0, mse / threshold)
        else:
            anomaly_score = 0.0
        
        # Mettre à jour
        embedding.reconstruction_error = mse
        embedding.anomaly_score = anomaly_score
        updated_count += 1
    
    # Commit
    if commit:
        session.commit()
        logger.info(f"✅ Updated {updated_count} embeddings")
    
    # Stats
    if mse_scores:
        logger.info(
            f"Anomaly score stats:\n"
            f"  Min: {min(mse_scores):.4f}\n"
            f"  Max: {max(mse_scores):.4f}\n"
            f"  Mean: {np.mean(mse_scores):.4f}\n"
            f"  Std: {np.std(mse_scores):.4f}\n"
            f"  Threshold: {threshold:.4f}"
        )


# ============================================================================
# 5. FONCTION AUXILIAIRE: BATCHPROCESS
# ============================================================================

def compute_anomaly_scores_batch(session, filing_ids: List[int], batch_size: int = 10):
    """
    Traiter plusieurs filings en batch.
    
    Args:
        session: SQLAlchemy session
        filing_ids: List d'IDs de filings
        batch_size: Nombre de filings par batch
    """
    logger.info(f"Processing {len(filing_ids)} filings in batches of {batch_size}")
    
    for i in range(0, len(filing_ids), batch_size):
        batch = filing_ids[i:i+batch_size]
        for filing_id in batch:
            try:
                compute_embeddings_anomaly_scores(session, filing_id, commit=True)
            except Exception as e:
                logger.error(f"Error processing filing {filing_id}: {e}", exc_info=True)


if __name__ == "__main__":
    # Test: Entraîner et scorer
    from app.db import SessionLocal
    
    session = SessionLocal()
    
    # Entraîner
    logger.info("=" * 70)
    logger.info("TRAINING PHASE")
    logger.info("=" * 70)
    trained_sectors = train_autoencoders_for_all_sectors(session, sector_codes=["7372", "3721"])
    
    # Scorer (exemple sur les 5 derniers filings)
    if trained_sectors:
        logger.info("=" * 70)
        logger.info("SCORING PHASE")
        logger.info("=" * 70)
        
        from app.db.models import Filing
        recent_filings = session.query(Filing.id).order_by(
            Filing.created_at.desc()
        ).limit(5).all()
        
        for filing_id, in recent_filings:
            compute_embeddings_anomaly_scores(session, filing_id)
    
    session.close()
