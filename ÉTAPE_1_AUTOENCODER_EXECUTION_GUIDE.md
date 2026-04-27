# 🚀 ÉTAPE 1: Sector Autoencoder - Guide Complet d'Exécution

**Statut**: PHASE 2 & 3 - Prêt pour entraînement et scoring  
**Créé**: 25 Avril 2026  
**Version**: 1.0  

---

## 📋 Table des Matières

1. [Architecture Récapitulatif](#architecture-récapitulatif)
2. [Prérequis et Installation](#prérequis)
3. [Phase 2: Entraînement](#phase-2-entraînement)
4. [Phase 3: Scoring](#phase-3-scoring)
5. [Validation et Diagnostics](#validation)
6. [Troubleshooting](#troubleshooting)

---

## Architecture Récapitulatif

### Fichiers Créés

```
signals/
  └─ sector_autoencoder.py         ← Module principal (PHASE 1 ✅)
  
train_autoencoder.py               ← Script ENTRAÎNEMENT (PHASE 2)
score_embeddings.py                ← Script SCORING (PHASE 3)

Tests/
  └─ test_sector_autoencoder_integration.py  ← Tests & validation
```

### Flux Complet

```
[PHASE 1: Architecture ✅]
    ↓
    VectorAutoencoder class (PyTorch model)
    SectorAutoencoderManager class (orchestration)
    
[PHASE 2: Entraînement]
    ↓
    train_autoencoder.py
    → Load embeddings par secteur (365 jours)
    → Train model (50 epochs)
    → Save model + threshold
    
[PHASE 3: Scoring]
    ↓
    score_embeddings.py
    → Load model
    → Compute MSE for each embedding
    → Normalize to anomaly_score [0, 1]
    → UPDATE database

Result: BD complète avec anomaly_score pour tous les embeddings ✅
```

---

## Prérequis

### 1. Vérifier les dépendances PyTorch

```bash
# Vérifier que PyTorch est installé
python -c "import torch; print(f'✅ PyTorch {torch.__version__}')"

# Résultat attendu:
# ✅ PyTorch 2.9.0+cu118
```

Si manquant, installer:

```bash
pip install torch==2.9.0 torchvision==0.18.0 torchaudio==2.9.0
```

### 2. Vérifier les embeddings en BD

```python
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding, Filing, Company

session = SessionLocal()

# Compter embeddings
embedding_count = session.query(Embedding).count()
print(f'Embeddings in DB: {embedding_count}')

# Compter secteurs
sectors = session.query(Company.sic_code).distinct().count()
print(f'Unique sectors: {sectors}')

# Exemples de secteurs
sample_sectors = session.query(Company.sic_code).distinct().limit(5).all()
print(f'Sample sectors: {[s[0] for s in sample_sectors]}')

session.close()
"
```

**Résultat attendu**:
```
Embeddings in DB: 5000+
Unique sectors: 15+
Sample sectors: ['7372', '3721', '7373', ...]
```

### 3. Créer le répertoire des modèles

```bash
mkdir -p data/autoencoder_models
ls -la data/autoencoder_models/
```

---

## Phase 2: Entraînement

### Objectif
Créer des modèles autoencoders **par secteur industriel** pour détecter les anomalies.

### Étape 1: Test Rapide (Optionnel)

Avant de traiter tous les secteurs, tester sur 1 secteur:

```bash
# Test sur secteur Software (7372)
python train_autoencoder.py --sector 7372 --verbose
```

**Résultat attendu**:
```
=======================================================================
PHASE 2: ENTRAÎNEMENT DES AUTOENCODERS
=======================================================================
Heure de démarrage: 2026-04-25T14:30:00.123456

Secteurs à traiter: ['7372']

INFO: Training autoencoder for sector 7372...
  Epoch 10/50: train_loss=0.0512, val_loss=0.0534
  Epoch 20/50: train_loss=0.0234, val_loss=0.0251
  ...
  Epoch 50/50: train_loss=0.0189, val_loss=0.0206

Sector 7372: Training complete
  Final train loss: 0.0189
  Final val loss: 0.0206
  Anomaly threshold (95th percentile): 0.0847

Model saved: data/autoencoder_models/sector_7372.pt
Threshold saved: data/autoencoder_models/sector_7372_threshold.pkl

✅ SUCCÈS: 1 secteur entraîné
Secteurs: 7372
=======================================================================
```

### Étape 2: Vérifier les Fichiers Créés

```bash
# Vérifier les modèles sauvegardés
ls -lh data/autoencoder_models/

# Résultat attendu:
# sector_7372.pt             (5-10 MB)
# sector_7372_threshold.pkl  (100 bytes)
```

### Étape 3: Entraîner Tous les Secteurs

```bash
# SANS verbose (plus rapide)
python train_autoencoder.py

# OU avec verbose pour voir les détails
python train_autoencoder.py --verbose

# OU secteurs spécifiques
python train_autoencoder.py --sector 7372 3721 2731
```

**Durée estimée**:
- Par secteur: 2-5 minutes
- Tous les secteurs (15-20): 30-60 minutes

### Étape 4: Vérifier l'Entraînement

```python
python -c "
from pathlib import Path
from signals.sector_autoencoder import SectorAutoencoderManager

mgr = SectorAutoencoderManager()

# Lister les modèles entraînés
models_dir = Path('data/autoencoder_models')
models = list(models_dir.glob('sector_*.pt'))
print(f'✅ Modèles entraînés: {len(models)}')

for model_file in sorted(models):
    sector = model_file.stem.split('_')[1]
    threshold_file = model_file.parent / f'sector_{sector}_threshold.pkl'
    if threshold_file.exists():
        print(f'  - Sector {sector}: ✅')
"
```

**Résultat attendu**:
```
✅ Modèles entraînés: 3
  - Sector 7372: ✅
  - Sector 3721: ✅
  - Sector 2731: ✅
```

---

## Phase 3: Scoring

### Objectif
Utiliser les modèles entraînés pour **scorer tous les embeddings** de la BD.

### Étape 1: Vérifier les Filings Non-Scorés

```python
python -c "
from app.db.session import SessionLocal
from app.db.models import Filing

session = SessionLocal()

unscored = session.query(Filing).filter(Filing.is_anomaly_scored == False).count()
print(f'Filings non-scorés: {unscored}')

total = session.query(Filing).count()
print(f'Total filings: {total}')

session.close()
"
```

### Étape 2: Test Rapide (Optionnel)

Scorer 1 filing pour tester:

```bash
# Score le filing 1
python score_embeddings.py --filing 1 --verbose
```

**Résultat attendu**:
```
=======================================================================
PHASE 3: SCORING DES EMBEDDINGS
=======================================================================
Heure de démarrage: 2026-04-25T14:45:00.123456

Filtré: 1 filings spécifiques
Total filings à traiter: 1

Processing en mode SÉQUENTIEL
[1/1] Processing filing 1...

Processing filing 1 (APPLE INC): 85 embeddings

Anomaly score stats:
  Min: 0.0234
  Max: 0.8756
  Mean: 0.3421
  Std: 0.1895
  Threshold: 0.0847

✅ Updated 85 embeddings

✅ SUCCÈS: 1 filings scorés

Total embeddings avec anomaly_score: 85
Anomaly Score Distribution:
  Min: 0.0234
  Max: 0.8756
  Avg: 0.3421

Heure de fin: 2026-04-25T14:45:15
=======================================================================
```

### Étape 3: Vérifier les Embeddings Scorés en BD

```python
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding
from sqlalchemy import func

session = SessionLocal()

# Count
scored = session.query(Embedding).filter(
    Embedding.anomaly_score.isnot(None)
).count()
print(f'Embeddings scorés: {scored}')

# Stats
stats = session.query(
    func.min(Embedding.anomaly_score),
    func.max(Embedding.anomaly_score),
    func.avg(Embedding.anomaly_score),
).filter(
    Embedding.anomaly_score.isnot(None)
).first()

if stats[0]:
    print(f'Anomaly Score stats:')
    print(f'  Min: {stats[0]:.4f}')
    print(f'  Max: {stats[1]:.4f}')
    print(f'  Avg: {stats[2]:.4f}')

session.close()
"
```

### Étape 4: Scorer Tous les Filings

**Option A: Séquentiellement (simple)**

```bash
python score_embeddings.py
```

**Option B: En Mode Batch (plus rapide pour beaucoup de filings)**

```bash
# Process 50 filings par batch
python score_embeddings.py --batch 50

# Process 100 filings par batch
python score_embeddings.py --batch 100
```

**Option C: Derniers N Filings**

```bash
# Score les 10 derniers filings
python score_embeddings.py --recent 10

# Score les 100 derniers filings
python score_embeddings.py --recent 100
```

**Option D: Filings d'une Company**

```bash
# Score tous les filings d'APPLE (company_id=1)
python score_embeddings.py --company 1
```

### Étape 5: Mode Dry-Run (Avant de Commiter)

Pour vérifier sans modifier la BD:

```bash
# Test sur 5 filings sans commit
python score_embeddings.py --recent 5 --dry-run --verbose

# Résultat: Tout s'affiche SAUF pas de commit
```

---

## Validation

### Tests Unitaires

```bash
python Tests/test_sector_autoencoder_integration.py
```

**Résultat attendu**:
```
========================================================================
SECTOR AUTOENCODER - TESTS & VALIDATION
========================================================================

[1/3] Unit Tests - Autoencoder Model
------------------------------------------------------------------------
✅ Autoencoder initialized successfully
✅ Forward pass works: input torch.Size([4, 1024]) -> output torch.Size([4, 1024])
✅ Encode works: torch.Size([4, 1024]) -> torch.Size([4, 256])

[2/3] Unit Tests - Manager
------------------------------------------------------------------------
✅ Manager initialized (device: cuda)
✅ Model saved successfully
✅ Model loaded successfully (threshold: 0.123)

[3/3] Unit Tests - Anomaly Scoring
------------------------------------------------------------------------
✅ MSE computation works: 0.123456
✅ Anomaly score normalization: MSE=0.123 → score=1.2300

[4/4] Database Integration
------------------------------------------------------------------------
✅ Embedding update in DB works

========================================================================
INTEGRATION TEST: Full Pipeline
========================================================================
📊 Database state:
   Filings: 500
   Embeddings: 5000

✅ ALL TESTS PASSED
========================================================================
```

### Vérification des Résultats en BD

```sql
-- Vérifier les anomaly_scores
SELECT 
    COUNT(*) as total_embeddings,
    COUNT(anomaly_score) as scored_embeddings,
    MIN(anomaly_score) as min_score,
    MAX(anomaly_score) as max_score,
    AVG(anomaly_score) as avg_score,
    STDDEV(anomaly_score) as stddev_score
FROM embeddings
WHERE anomaly_score IS NOT NULL;

-- Résultat attendu:
-- total_embeddings | scored_embeddings | min_score | max_score | avg_score | stddev_score
-- 5000             | 5000              | 0.0234    | 0.8756    | 0.3421    | 0.1895

-- Top 10 paragraphes anomaleux
SELECT 
    filing_id,
    company_id,
    chunk_idx,
    anomaly_score,
    SUBSTRING(text, 1, 80) as text_preview
FROM embeddings
WHERE anomaly_score IS NOT NULL
ORDER BY anomaly_score DESC
LIMIT 10;
```

---

## Troubleshooting

### ❌ Erreur: "No embeddings found"

**Cause**: Aucun embedding dans la BD

**Solution**:
```bash
# Vérifier embeddings
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding

session = SessionLocal()
count = session.query(Embedding).count()
print(f'Embeddings: {count}')
session.close()
"

# Si 0: Lancer le pipeline d'ingestion/embedding d'abord
python run_news_pipeline.py
python run_form4_pipeline.py
python run_signals.py
```

### ❌ Erreur: "CUDA out of memory"

**Cause**: GPU insuffisant

**Solution**:
```python
# Réduire la batch size dans sector_autoencoder.py:
AUTOENCODER_BATCH_SIZE = 16  # De 32 à 16
```

### ❌ Erreur: "Model not found for sector X"

**Cause**: Secteur pas encore entraîné

**Solution**:
```bash
# Entraîner le secteur manquant
python train_autoencoder.py --sector 7372
```

### ⚠️ Performance Lente

**Optimisations**:

1. **Batch processing** (2-3x plus rapide):
```bash
python score_embeddings.py --batch 100
```

2. **GPU acceleration**:
```python
# Vérifier GPU disponible
python -c "import torch; print(torch.cuda.is_available())"

# Si False: Installer CUDA drivers
```

3. **Parallélisation** (Advanced):
```python
# Modifier compute_anomaly_scores_batch() pour ThreadPool
```

---

## 📊 Checklist d'Exécution

### AVANT de commencer
- [ ] ✅ PostgreSQL running et connecté
- [ ] ✅ PyTorch installé (`torch==2.9.0`)
- [ ] ✅ Embeddings existent en BD (5000+)
- [ ] ✅ Répertoire `data/autoencoder_models/` existe

### Phase 2: Entraînement
- [ ] ✅ Test sur 1 secteur: `python train_autoencoder.py --sector 7372`
- [ ] ✅ Tous les secteurs: `python train_autoencoder.py`
- [ ] ✅ Vérifier modèles: `ls -la data/autoencoder_models/`

### Phase 3: Scoring
- [ ] ✅ Tests unitaires: `python Tests/test_sector_autoencoder_integration.py`
- [ ] ✅ Test dry-run: `python score_embeddings.py --recent 5 --dry-run`
- [ ] ✅ Score filings: `python score_embeddings.py`
- [ ] ✅ Vérifier BD: `SELECT COUNT(*) FROM embeddings WHERE anomaly_score IS NOT NULL`

### Après Completion
- [ ] ✅ Étape 1 complétée
- [ ] ✅ Prêt pour ÉTAPE 2 (Convergence Signal)

---

## 🎯 Prochaines Étapes

Une fois ÉTAPE 1 complétée:

1. **ÉTAPE 2: Composite Signals Améliorés**
   - Triplet Convergence Signal (RLDS+GCE+ITA)
   - Fichier: `signals/composite_engine.py`

2. **ÉTAPE 3: Quality Monitoring (Sentinel)**
   - Freshness checks
   - Insider sales detection
   - Fichier: `signals/sentinel.py`

3. **ÉTAPE 4: LLM Explicability**
   - Narration des résultats
   - Fichier: `signals/explainability_client.py`

---

## 📞 Support

Pour déboguer:

```bash
# Mode verbose complet
python train_autoencoder.py --verbose
python score_embeddings.py --verbose

# Voir les logs
tail -f logs/finpulse.log

# Tests détaillés
python Tests/test_sector_autoencoder_integration.py --debug
```

---

**Créé**: 25 Avril 2026  
**Status**: ✅ Prêt pour exécution  
**Version**: 1.0  
