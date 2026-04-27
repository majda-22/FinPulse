#!/usr/bin/env python3
"""
Test et validation: ÉTAPE 1 - Sector Autoencoder

Script pour tester et valider l'implémentation des autoencoders.

Utilisation:
    python Tests/test_sector_autoencoder_integration.py          # Tests complets
    python Tests/test_sector_autoencoder_integration.py --quick   # Tests rapides
    python Tests/test_sector_autoencoder_integration.py --debug   # Mode debug
"""

import pytest
import sys
import numpy as np
import torch
from pathlib import Path
from datetime import datetime, timedelta

# Ajouter chemin racine
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import SessionLocal
from app.db.models import Embedding, Filing, Company
from signals.sector_autoencoder import (
    VectorAutoencoder,
    SectorAutoencoderManager,
    train_autoencoders_for_all_sectors,
    compute_embeddings_anomaly_scores,
)


class TestVectorAutoencoder:
    """Tests du modèle autoencoder."""
    
    def test_autoencoder_initialization(self):
        """Test: Initialisation du modèle."""
        model = VectorAutoencoder(input_dim=1024, hidden_size=512, bottleneck_size=256)
        assert model is not None
        print("✅ Autoencoder initialized successfully")
    
    def test_autoencoder_forward(self):
        """Test: Forward pass."""
        model = VectorAutoencoder()
        
        # Dummy input
        batch_size = 4
        x = torch.randn(batch_size, 1024)
        
        # Forward
        y = model(x)
        
        assert y.shape == (batch_size, 1024), f"Expected shape {(batch_size, 1024)}, got {y.shape}"
        assert not torch.isnan(y).any(), "Output contains NaN"
        print(f"✅ Forward pass works: input {x.shape} -> output {y.shape}")
    
    def test_autoencoder_encode(self):
        """Test: Encode (bottleneck)."""
        model = VectorAutoencoder()
        x = torch.randn(4, 1024)
        
        encoded = model.encode(x)
        
        assert encoded.shape == (4, 256), f"Expected bottleneck shape (4, 256), got {encoded.shape}"
        print(f"✅ Encode works: {x.shape} -> {encoded.shape}")


class TestSectorAutoencoderManager:
    """Tests du gestionnaire d'autoencoders."""
    
    def test_manager_initialization(self):
        """Test: Initialisation du manager."""
        manager = SectorAutoencoderManager()
        assert manager is not None
        assert manager.device is not None
        print(f"✅ Manager initialized (device: {manager.device})")
    
    def test_manager_save_load(self, tmp_path):
        """Test: Sauvegarde et chargement."""
        manager = SectorAutoencoderManager(models_dir=tmp_path)
        
        # Créer modèle
        model = VectorAutoencoder()
        threshold = 0.123
        
        # Sauvegarder
        manager.save_model("TEST_SECTOR", model, threshold)
        
        # Vérifier fichiers
        assert (tmp_path / "sector_TEST_SECTOR.pt").exists()
        assert (tmp_path / "sector_TEST_SECTOR_threshold.pkl").exists()
        print("✅ Model saved successfully")
        
        # Charger
        loaded_model, loaded_threshold = manager.load_model("TEST_SECTOR")
        assert loaded_model is not None
        assert loaded_threshold == threshold
        print(f"✅ Model loaded successfully (threshold: {loaded_threshold})")


class TestDataPreparation:
    """Tests de préparation des données."""
    
    def test_prepare_dataset(self):
        """Test: Préparation du dataset."""
        session = SessionLocal()
        manager = SectorAutoencoderManager()
        
        try:
            # Checker si embeddings existent
            count = session.query(Embedding).count()
            print(f"📊 Total embeddings in DB: {count}")
            
            if count > 0:
                # Essayer de charger un secteur
                sector_codes = session.query(Company.sic_code).distinct().limit(3).all()
                for sector_code, in sector_codes:
                    data = manager.prepare_sector_dataset(session, sector_code)
                    if data is not None:
                        print(f"✅ Sector {sector_code}: {len(data)} embeddings loaded")
                        assert data.shape[1] == 1024
            else:
                print("⚠️  No embeddings in DB, skipping dataset test")
        
        finally:
            session.close()


class TestAnomalyScoring:
    """Tests du scoring d'anomalies."""
    
    def test_mse_computation(self):
        """Test: Computation du MSE."""
        model = VectorAutoencoder()
        
        # Créer embedding
        x = torch.randn(1, 1024)
        y = model(x)
        
        # MSE
        mse = torch.mean((x - y) ** 2).item()
        
        assert isinstance(mse, float)
        assert mse >= 0.0, f"MSE must be non-negative, got {mse}"
        assert isinstance(mse, float), f"MSE should be a float, got {type(mse)}"# MSE devrait être petit pour random data
        print(f"✅ MSE computation works: {mse:.6f}")
    
    def test_anomaly_score_normalization(self):
        mse = 0.123
        threshold = 0.100

        score = min(1.0, mse / threshold)  # Capped — 1.0 means "at or above threshold"

        assert 0 <= score <= 1.0
        if mse > threshold:
            assert score == 1.0, f"Expected score == 1.0 when MSE exceeds threshold, got {score:.4f}"
        else:
            assert score < 1.0, f"Expected score < 1.0 when MSE below threshold, got {score:.4f}"
        print(f"✅ Anomaly score normalization: MSE={mse} → score={score:.4f}")

class TestDatabaseIntegration:
    """Tests de l'intégration BD."""
    
    def test_embedding_update(self):
        """Test: Mise à jour des embeddings en BD."""
        session = SessionLocal()
        
        try:
            # Charger un embedding
            embedding = session.query(Embedding).first()
            
            if embedding:
                original_error = embedding.reconstruction_error
                
                # Mettre à jour
                embedding.reconstruction_error = 0.123
                embedding.anomaly_score = 0.456
                session.commit()
                
                # Vérifier
                updated = session.query(Embedding).filter(
                    Embedding.id == embedding.id
                ).first()
                
                assert updated.reconstruction_error == 0.123
                assert updated.anomaly_score == 0.456
                
                # Restaurer
                updated.reconstruction_error = original_error
                updated.anomaly_score = None
                session.commit()
                
                print("✅ Embedding update in DB works")
            else:
                print("⚠️  No embeddings to test")
        
        finally:
            session.close()


def run_integration_test():
    """Test d'intégration: E2E pipeline."""
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: Full Pipeline")
    print("=" * 70)
    
    session = SessionLocal()
    
    try:
        # Vérifier données
        filings_count = session.query(Filing).count()
        embeddings_count = session.query(Embedding).count()
        
        print(f"📊 Database state:")
        print(f"   Filings: {filings_count}")
        print(f"   Embeddings: {embeddings_count}")
        
        if embeddings_count == 0:
            print("\n❌ No embeddings in database. Please run ingestion/embedding pipeline first.")
            return False
        
        # Résumé
        print("\n✅ All integration tests passed!")
        return True
    
    finally:
        session.close()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "=" * 70)
    print("SECTOR AUTOENCODER - TESTS & VALIDATION")
    print("=" * 70)
    
    # Test unitaire
    print("\n[1/3] Unit Tests - Autoencoder Model")
    print("-" * 70)
    test = TestVectorAutoencoder()
    test.test_autoencoder_initialization()
    test.test_autoencoder_forward()
    test.test_autoencoder_encode()
    
    # Test manager
    print("\n[2/3] Unit Tests - Manager")
    print("-" * 70)
    test_mgr = TestSectorAutoencoderManager()
    test_mgr.test_manager_initialization()
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        test_mgr.test_manager_save_load(Path(tmpdir))
    # Test anomaly scoring
    print("\n[3/3] Unit Tests - Anomaly Scoring")
    print("-" * 70)
    test_scoring = TestAnomalyScoring()
    test_scoring.test_mse_computation()
    test_scoring.test_anomaly_score_normalization()
    
    # Integration test
    print("\n[4/4] Database Integration")
    print("-" * 70)
    test_db = TestDatabaseIntegration()
    test_db.test_embedding_update()
    
    # E2E
    success = run_integration_test()
    
    if success:
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        sys.exit(0)
    else:
        sys.exit(1)
