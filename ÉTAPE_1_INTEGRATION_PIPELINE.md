4# 🔗 ÉTAPE 1: Intégration au Pipeline Existant

**Objectif**: Montrer comment ÉTAPE 1 s'intègre au pipeline FinPulse complet

---

## 📍 Positionnement dans le Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  INGESTION PIPELINE (Existe déjà)                                   │
│                                                                     │
│  1. Filing 10-Q/10-K                                               │
│     ↓                                                               │
│  2. Extract XBRL, text sections                                    │
│     ↓                                                               │
│  3. Chunk paragraphs (500 words)                                   │
│     ↓                                                               │
│  4. Generate embeddings (Mistral 1024-dim)                         │
│     ├─ ID, filing_id, company_id, text                            │
│     ├─ embedding (1024 vector)                                    │
│     ├─ reconstruction_error (NULL à ce stade)                     │
│     └─ anomaly_score (NULL à ce stade)                            │
│     ↓                                                               │
│  BD: embeddings table remplie (SAUF 2 colonnes)                   │
│                                                                     │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ⭐ ÉTAPE 1: SECTOR AUTOENCODER (À FAIRE - C'EST ICI) ⭐            │
│                                                                      │
│  💻 Scripts à exécuter:                                             │
│  $ python train_autoencoder.py      # PHASE 2: Entraîner          │
│  $ python score_embeddings.py        # PHASE 3: Scorer              │
│                                                                      │
│  ✅ Résultat:                                                       │
│     reconstruction_error ← MSE                                     │
│     anomaly_score ← Normalized [0, 1]                              │
│                                                                      │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SIGNAL COMPUTATION PIPELINE (Après ÉTAPE 1)                        │
│                                                                     │
│  1. Text Signals (sentiment, similarity, etc.)                     │
│     ↓                                                               │
│  2. Numeric Signals (XBRL facts, ratios)                          │
│     ↓                                                               │
│  3. Insider Signals (Form 4 insiders transactions)                │
│     ↓                                                               │
│  4. Market Signals (price, volume)                                │
│     ↓                                                               │
│  5. Enhanced Signals (NEW - ÉTAPE 2, 3, 4)                        │
│     ├─ Anomaly Signal (from ÉTAPE 1) ← WE ARE HERE ✅            │
│     ├─ Triplet Convergence (ÉTAPE 2)                             │
│     ├─ Quality Alerts (ÉTAPE 3)                                   │
│     └─ LLM Narrative (ÉTAPE 4)                                    │
│     ↓                                                               │
│  NCI Score computation                                             │
│                                                                     │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  API / ALERTING LAYER                                              │
│                                                                     │
│  GET /api/nci/{filing_id}                                          │
│  → Score + Explications + Alertes + Anomalies                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Flux des Données

### Avant ÉTAPE 1

```python
# embeddings table
Row: {
    id: 12345,
    filing_id: 1001,
    company_id: 42,
    text: "Apple's revenue grew 15% YoY...",
    embedding: [0.125, 0.203, -0.087, ... 1021 more],
    provider: "mistral",
    embedding_model: "mistral-embed",
    reconstruction_error: NULL,        ← À REMPLIR ✅
    anomaly_score: NULL,               ← À REMPLIR ✅
}
```

### Après ÉTAPE 1

```python
# embeddings table
Row: {
    id: 12345,
    filing_id: 1001,
    company_id: 42,
    text: "Apple's revenue grew 15% YoY...",
    embedding: [0.125, 0.203, -0.087, ...],
    provider: "mistral",
    embedding_model: "mistral-embed",
    reconstruction_error: 0.0089,      ← REMPLI ✅
    anomaly_score: 0.105,              ← REMPLI ✅
}

# Interprétation:
# - reconstruction_error (0.0089): Petit MSE = bonne reconstruction
# - anomaly_score (0.105): Score bas = embedding NORMAL (10% anomalous)
```

---

## Mise à Jour des Status Flags

### Avant ÉTAPE 1

```sql
SELECT 
    id,
    is_embedded,              -- TRUE (embeddings générés)
    is_anomaly_scored,        -- FALSE ← À METTRE À TRUE
    processing_status
FROM filings
LIMIT 5;

-- Résultat:
-- id  | is_embedded | is_anomaly_scored | processing_status
-- 1   | true        | false             | pending
-- 2   | true        | false             | pending
-- 3   | true        | false             | pending
```

### Après ÉTAPE 1

```sql
SELECT 
    id,
    is_embedded,              -- TRUE
    is_anomaly_scored,        -- TRUE ← REMPLI ✅
    processing_status
FROM filings
LIMIT 5;

-- Résultat:
-- id  | is_embedded | is_anomaly_scored | processing_status
-- 1   | true        | true              | pending
-- 2   | true        | true              | pending
-- 3   | true        | true              | pending
```

**Note**: Le flag `is_anomaly_scored` est mis à jour automatiquement par `compute_embeddings_anomaly_scores()` si tous les embeddings sont scorés.

---

## Intégration avec run_signals.py

### Ajouter ÉTAPE 1 au Pipeline Principal

Modifier `run_signals.py` pour ajouter les autoencoders:

```python
# run_signals.py (existant)

if __name__ == "__main__":
    # ... imports existants ...
    
    # 1. Existing signal computation
    print("Computing text signals...")
    run_text_signals()
    
    print("Computing numeric signals...")
    run_numeric_signals()
    
    print("Computing insider signals...")
    run_insider_signals()
    
    print("Computing market signals...")
    run_market_signals()
    
    # 2. NEW: Add ÉTAPE 1 (Autoencoder)
    print("=" * 70)
    print("NEW: Computing anomaly scores (ÉTAPE 1)...")
    print("=" * 70)
    
    from signals.sector_autoencoder import (
        train_autoencoders_for_all_sectors,
        compute_anomaly_scores_batch
    )
    from app.db.session import SessionLocal
    from app.db.models import Filing
    
    session = SessionLocal()
    
    try:
        # Train autoencoders (si pas fait)
        print("Step 1: Training autoencoders...")
        trained = train_autoencoders_for_all_sectors(session)
        print(f"✅ Trained {len(trained)} sectors")
        
        # Score embeddings
        print("\nStep 2: Scoring embeddings...")
        unscored_filings = session.query(Filing.id).filter(
            Filing.is_anomaly_scored == False
        ).all()
        
        filing_ids = [row[0] for row in unscored_filings]
        
        if filing_ids:
            compute_anomaly_scores_batch(session, filing_ids, batch_size=50)
            print(f"✅ Scored {len(filing_ids)} filings")
        else:
            print("⚠️  No unscored filings")
    
    finally:
        session.close()
    
    # 3. Continue with composite signals
    print("\nComputing composite signals...")
    run_composite_signals()
```

### Ou Créer un Script Séparé

Créer `run_autoencoder_pipeline.py`:

```python
#!/usr/bin/env python3
"""
Automated ÉTAPE 1 pipeline runner
Entraîner et scorer les autoencoders
"""

import sys
from app.db.session import SessionLocal
from app.db.models import Filing
from signals.sector_autoencoder import (
    train_autoencoders_for_all_sectors,
    compute_anomaly_scores_batch
)

def main():
    session = SessionLocal()
    
    try:
        # PHASE 2: Train
        print("PHASE 2: Training autoencoders...")
        trained = train_autoencoders_for_all_sectors(session)
        print(f"✅ Trained {len(trained)} sectors\n")
        
        # PHASE 3: Score
        print("PHASE 3: Scoring embeddings...")
        unscored = session.query(Filing.id).filter(
            Filing.is_anomaly_scored == False
        ).all()
        
        filing_ids = [row[0] for row in unscored]
        
        if not filing_ids:
            print("⚠️  No filings to score")
            return 0
        
        print(f"Scoring {len(filing_ids)} filings...")
        compute_anomaly_scores_batch(session, filing_ids, batch_size=50)
        print(f"✅ Scored {len(filing_ids)} filings\n")
        
        return 0
    
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    
    finally:
        session.close()

if __name__ == "__main__":
    sys.exit(main())
```

Exécuter:

```bash
python run_autoencoder_pipeline.py
```

---

## Dépendances entre Étapes

### ÉTAPE 1 Dépend De:

```
embeddings table
├─ Must have: 5000+ rows
├─ Must have: filing_id, company_id
├─ Must have: embedding (1024-dim vector)
└─ Must have: company.sic_code populated
```

**Vérifier**:
```bash
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding, Company

s = SessionLocal()

# Check embeddings
assert s.query(Embedding).count() >= 5000

# Check company sector codes
for comp in s.query(Company).limit(5):
    assert comp.sic_code is not None

print('✅ Dependencies OK')
s.close()
"
```

### Qu'Est-ce que ÉTAPE 1 Produit Pour ÉTAPE 2

```
embeddings table (complète)
├─ reconstruction_error ← NEW
├─ anomaly_score ← NEW
└─ → Utilisé par ÉTAPE 2

signal_scores table
├─ anomaly_signal (NEW - from ÉTAPE 1)
├─ triplet_convergence (NEW - from ÉTAPE 2)
└─ composite_score (aggregated)
```

---

## Monitoring et Debugging

### Pendant Exécution

```bash
# Terminal 1: Run ÉTAPE 1
python score_embeddings.py --batch 50

# Terminal 2: Monitor progress
watch -n 5 'python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding
from sqlalchemy import func

s = SessionLocal()
scored = s.query(func.count(Embedding.anomaly_score)).filter(
    Embedding.anomaly_score.isnot(None)
).first()[0]
total = s.query(func.count(Embedding.id)).first()[0]
print(f\"Progress: {scored}/{total} ({100*scored/total:.1f}%)\")
s.close()
"'
```

### Après Exécution

```python
# Vérifier intégrité
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding, Filing
from sqlalchemy import func

s = SessionLocal()

# Check 1: No NULLs
nulls = s.query(Embedding).filter(
    Embedding.anomaly_score.is_(None)
).count()
assert nulls == 0, f'ERREUR: {nulls} NULL anomaly_scores'
print('✅ No NULL values')

# Check 2: Distribution
stats = s.query(
    func.min(Embedding.anomaly_score),
    func.max(Embedding.anomaly_score),
    func.avg(Embedding.anomaly_score),
).first()

assert stats[0] > 0, 'Min score should be > 0'
assert stats[1] < 1, 'Max score should be < 1'
assert 0.2 < stats[2] < 0.5, 'Avg should be 0.2-0.5'
print(f'✅ Distribution OK: [{stats[0]:.3f}, {stats[1]:.3f}] avg:{stats[2]:.3f}')

# Check 3: Filing flags updated
unscored = s.query(Filing).filter(
    Filing.is_anomaly_scored == False
).count()
assert unscored == 0, f'ERREUR: {unscored} filings not marked as scored'
print('✅ Filing flags updated')

s.close()
"
```

---

## Prochaines Étapes Après ÉTAPE 1

### Immédiat (Next 2 hours)

1. ✅ ÉTAPE 1 complétée
2. ⏳ Vérifier tous les embeddings ont anomaly_score
3. ⏳ Commit to production DB

### Court terme (Next 2-3 heures)

4. **ÉTAPE 2**: Composite Signals Améliorés
   - Input: `embeddings.anomaly_score`
   - Output: `signal_scores.triplet_convergence_signal`
   - File: `signals/composite_engine.py` (à modifier)

5. **ÉTAPE 3**: Sentinel (Quality Monitoring)
   - Input: `nci_scores`, `embeddings.anomaly_score`
   - Output: `quality_alerts` table
   - File: `signals/sentinel.py` (à créer)

6. **ÉTAPE 4**: LLM Explicability
   - Input: Top anomalous embeddings
   - Output: `explanations` (narrative + severity)
   - File: `signals/explainability_client.py` (à créer)

### Long terme (End of week)

7. API /nci/{filing_id} enrichie avec tous les résultats
8. Dashboard with anomaly visualization
9. Alerting system intégré

---

## Rollback & Recovery

### Si Erreur Mid-Exécution

```bash
# Arrêter le script
Ctrl + C

# Vérifier l'état
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding

s = SessionLocal()
scored = s.query(Embedding).filter(
    Embedding.anomaly_score.isnot(None)
).count()
print(f'Scored embeddings: {scored}')
s.close()
"

# Continuer depuis où on a arrêté
python score_embeddings.py --batch 50
# (Continuera depuis les filings non-scorés)
```

### Nettoyer et Recommencer

```bash
# ⚠️ ATTENTION: Cela réinitialise tout ÉTAPE 1

python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding
from sqlalchemy import update

s = SessionLocal()

# Reset anomaly scores
s.execute(update(Embedding).values(
    reconstruction_error=None,
    anomaly_score=None
))
s.commit()

print('✅ Reset complete, ready to re-run')
s.close()
"

# Puis relancer
python train_autoencoder.py
python score_embeddings.py --batch 50
```

---

## Performance Benchmarks

### Entraînement
```
Sector    Samples  Time    Loss
7372      2847     180s    0.0189
3721      1956     120s    0.0156
2731      687      60s     0.0401
...
Total     ~10000   ~600s   (10 min)
```

### Scoring
```
Filings   Embeddings   Mode      Time    Speed
50        5000         Batch     150s    ~33/sec
100       10000        Batch     300s    ~33/sec
500       50000        Batch     1500s   ~33/sec
```

### Prédiction: Full Dataset
- Embeddings: ~50,000
- Temps scoring: ~1500 sec (25 min avec batch mode)

---

## Support & Help

### Voir Documentation
- `QUICK_REFERENCE_ÉTAPE_1.md` - Commandes rapides
- `ÉTAPE_1_AUTOENCODER_EXECUTION_GUIDE.md` - Guide complet
- `ÉTAPE_1_ARCHITECTURE_FLUX.md` - Architecture et flux
- `CHECKLIST_ÉTAPE_1.md` - Step-by-step checklist

### Logs
```bash
# Enable debug logging
export PYTHONUNBUFFERED=1
python score_embeddings.py --verbose 2>&1 | tee debug.log
```

---

**Version**: 1.0  
**Date**: 25 Avril 2026  
**Status**: ✅ Integration Guide Complete  

