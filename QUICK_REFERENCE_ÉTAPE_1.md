# 🔄 ÉTAPE 1: Quick Reference - Cheat Sheet

**Copier/Coller les commandes directement** 👇

---

## ✅ Préparation (5 min)

### 1. Vérifier les dépendances

```bash
# PyTorch
python -c "import torch; print(f'PyTorch {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}')"

# SQLAlchemy
python -c "import sqlalchemy; print(f'SQLAlchemy {sqlalchemy.__version__}')"

# BD: Embeddings
python -c "from app.db.session import SessionLocal; from app.db.models import Embedding; s = SessionLocal(); print(f'Embeddings: {s.query(Embedding).count()}'); s.close()"
```

### 2. Créer le répertoire des modèles

```bash
mkdir -p data/autoencoder_models
ls -la data/autoencoder_models/
```

---

## 🏋️ Phase 2: Entraînement (30-60 min)

### Option A: Test Rapide (1 secteur)

```bash
# Test sur Software (7372)
python train_autoencoder.py --sector 7372 --verbose

# Résultat: 1 modèle créé
# ✅ data/autoencoder_models/sector_7372.pt
# ✅ data/autoencoder_models/sector_7372_threshold.pkl
```

### Option B: Tous les Secteurs

```bash
# Entraîner TOUS (auto-detection)
python train_autoencoder.py

# Ou spécifier les secteurs
python train_autoencoder.py --sector 7372 3721 2731 1320

# Verbose
python train_autoencoder.py --verbose
```

### Option C: Vérifier les Modèles

```bash
# Lister les modèles créés
ls -lh data/autoencoder_models/

# Vérifier le nombre
python -c "from pathlib import Path; models = list(Path('data/autoencoder_models').glob('sector_*.pt')); print(f'Models trained: {len(models)}')"
```

---

## 🎯 Phase 3: Scoring (10-60 min selon volume)

### Option A: Test Rapide (1 filing)

```bash
# Score 1 filing
python score_embeddings.py --filing 1 --verbose

# Mode dry-run (pas de commit)
python score_embeddings.py --filing 1 --dry-run --verbose
```

### Option B: Tous les Filings Non-Scorés

```bash
# Score tous les filings sans anomaly_score
python score_embeddings.py

# Avec verbose
python score_embeddings.py --verbose
```

### Option C: Derniers N Filings

```bash
# Score 10 derniers filings
python score_embeddings.py --recent 10

# Score 100 derniers
python score_embeddings.py --recent 100
```

### Option D: En Mode Batch (RECOMMENDED pour volume)

```bash
# Score par batch de 50 filings
python score_embeddings.py --batch 50

# Batch 100 (plus rapide)
python score_embeddings.py --batch 100

# Batch 200 (très rapide mais plus de mémoire)
python score_embeddings.py --batch 200
```

### Option E: Filings d'une Company

```bash
# Score tous les filings d'APPLE (company_id = 1)
python score_embeddings.py --company 1

# Score company_id = 42
python score_embeddings.py --company 42
```

### Option F: Filings Multiples Spécifiques

```bash
# Score filings 1, 2, 3
python score_embeddings.py --filing 1 2 3

# Score filings 100 à 110
python score_embeddings.py --filing 100 101 102 103 104 105 106 107 108 109 110
```

---

## 🧪 Tests & Validation

### Tests Unitaires Complets

```bash
python Tests/test_sector_autoencoder_integration.py
```

### Vérifier les Résultats en BD

```python
# Nombre d'embeddings scorés
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding
from sqlalchemy import func

session = SessionLocal()
stats = session.query(
    func.count(Embedding.id).label('total'),
    func.count(Embedding.anomaly_score).label('scored'),
    func.min(Embedding.anomaly_score),
    func.max(Embedding.anomaly_score),
    func.avg(Embedding.anomaly_score),
).first()

print(f'Total embeddings: {stats.total}')
print(f'Scored embeddings: {stats.scored}')
if stats[2]:
    print(f'Score range: [{stats[2]:.4f}, {stats[3]:.4f}]')
    print(f'Average score: {stats[4]:.4f}')

session.close()
"
```

### Top 10 Paragraphes Anomaleux

```python
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding

session = SessionLocal()
top_anomalies = session.query(
    Embedding.id,
    Embedding.filing_id,
    Embedding.anomaly_score,
    Embedding.text
).filter(
    Embedding.anomaly_score.isnot(None)
).order_by(
    Embedding.anomaly_score.desc()
).limit(10).all()

for idx, (emb_id, filing_id, score, text) in enumerate(top_anomalies, 1):
    print(f'{idx}. Filing {filing_id} | Score: {score:.4f}')
    print(f'   Text: {text[:100]}...\n')

session.close()
"
```

---

## 🐛 Troubleshooting Rapide

### Erreur: "No embeddings found"

```bash
# Vérifier embeddings en BD
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding
s = SessionLocal()
print('Embeddings:', s.query(Embedding).count())
s.close()
"

# Si 0 → Lancer d'abord les pipelines d'ingestion
python run_news_pipeline.py
python run_form4_pipeline.py
python run_signals.py
```

### Erreur: "CUDA out of memory"

```python
# Réduire batch size dans signals/sector_autoencoder.py ligne 33:
# Changer: AUTOENCODER_BATCH_SIZE = 32
# En:      AUTOENCODER_BATCH_SIZE = 16
```

### Erreur: "Model not found for sector X"

```bash
# Entraîner le secteur manquant
python train_autoencoder.py --sector 7372
```

### Lent / Timeout

```bash
# Utiliser batch mode (2-5x plus rapide)
python score_embeddings.py --batch 100  # Au lieu de --batch 1 ou rien

# Ou limiter aux derniers filings
python score_embeddings.py --recent 50
```

---

## 📊 Checklist Full Auto

Copier/exécuter ce bloc complet:

```bash
#!/bin/bash

echo "=== ÉTAPE 1: FULL AUTOENCODER PIPELINE ==="

# Préparation
echo "1. Préparation..."
mkdir -p data/autoencoder_models

# Phase 2: Entraînement
echo "2. Entraînement des modèles..."
python train_autoencoder.py

# Phase 3: Scoring
echo "3. Scoring des embeddings..."
python score_embeddings.py --batch 50

# Validation
echo "4. Validation..."
python Tests/test_sector_autoencoder_integration.py

# Stats finales
echo ""
echo "5. Stats finales:"
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding, Filing
from sqlalchemy import func

session = SessionLocal()

embeddings_scored = session.query(Embedding).filter(
    Embedding.anomaly_score.isnot(None)
).count()

filings_scored = session.query(Filing).filter(
    Filing.is_anomaly_scored == True
).count()

print(f'✅ Embeddings scorés: {embeddings_scored}')
print(f'✅ Filings scorés: {filings_scored}')

session.close()
"

echo ""
echo "✅ ÉTAPE 1 COMPLÉTÉE!"
```

Sauvegarder dans `run_etape1.sh` et exécuter:

```bash
chmod +x run_etape1.sh
./run_etape1.sh
```

---

## 📝 Commandes Bonus

### Voir les logs en temps réel

```bash
# Pendant l'exécution, dans un autre terminal
tail -f logs/finpulse.log | grep "autoencoder"
```

### Nettoyer les anciens modèles

```bash
# ⚠️ ATTENTION: Cela supprime les modèles existants
rm -rf data/autoencoder_models/*
```

### Explorer les modèles

```python
# Vérifier l'architecture du modèle
python -c "
import torch
from signals.sector_autoencoder import VectorAutoencoder

model = VectorAutoencoder()
print(model)
print(f'\nNombre de paramètres: {sum(p.numel() for p in model.parameters())}')
"

# Résultat:
# VectorAutoencoder(
#   (encoder): Sequential(...)
#   (decoder): Sequential(...)
# )
# Nombre de paramètres: 1,585,408
```

### Performance: Benchmark

```python
import time
import torch
from signals.sector_autoencoder import VectorAutoencoder

model = VectorAutoencoder()
x = torch.randn(1024, 1024)  # 1024 embeddings

# Mesurer le temps
start = time.time()
with torch.no_grad():
    y = model(x)
elapsed = time.time() - start

print(f"1024 embeddings en {elapsed:.3f}s")
print(f"Throughput: {1024 / elapsed:.0f} embeddings/sec")

# Résultat attendu:
# 1024 embeddings en 0.023s
# Throughput: 44521 embeddings/sec
```

---

## 🎯 Status Checker

Vérifier l'état d'avancement:

```python
#!/usr/bin/env python3
from app.db.session import SessionLocal
from app.db.models import Filing, Embedding
from sqlalchemy import func
from pathlib import Path

session = SessionLocal()

print("=" * 60)
print("ÉTAPE 1: SECTOR AUTOENCODER - STATUS")
print("=" * 60)

# Modèles
models = list(Path('data/autoencoder_models').glob('sector_*.pt'))
print(f"\n[Entraînement]")
print(f"  Modèles entraînés: {len(models)}")
if models:
    print(f"  Secteurs: {', '.join([m.stem.split('_')[1] for m in models])}")

# Scoring
print(f"\n[Scoring]")
total_embeddings = session.query(Embedding).count()
scored_embeddings = session.query(Embedding).filter(
    Embedding.anomaly_score.isnot(None)
).count()
print(f"  Total embeddings: {total_embeddings}")
print(f"  Embeddings scorés: {scored_embeddings}")
print(f"  Progression: {100 * scored_embeddings / max(total_embeddings, 1):.1f}%")

# Filings
print(f"\n[Filings]")
total_filings = session.query(Filing).count()
anomaly_scored = session.query(Filing).filter(
    Filing.is_anomaly_scored == True
).count()
print(f"  Total filings: {total_filings}")
print(f"  Filings scorés: {anomaly_scored}")
print(f"  Progression: {100 * anomaly_scored / max(total_filings, 1):.1f}%")

# Stats
print(f"\n[Quality Stats]")
stats = session.query(
    func.min(Embedding.anomaly_score),
    func.max(Embedding.anomaly_score),
    func.avg(Embedding.anomaly_score),
).filter(
    Embedding.anomaly_score.isnot(None)
).first()

if stats[0]:
    print(f"  Min score: {stats[0]:.4f}")
    print(f"  Max score: {stats[1]:.4f}")
    print(f"  Avg score: {stats[2]:.4f}")

print("\n" + "=" * 60)

session.close()
```

Sauvegarder en `check_status.py` et exécuter:

```bash
python check_status.py
```

---

## 🚀 Résumé des Phases

| Phase | Tâche | Commande | Durée |
|-------|-------|----------|-------|
| **2** | Entraîner | `python train_autoencoder.py` | 30-60 min |
| **3** | Scorer (batch) | `python score_embeddings.py --batch 100` | 20-50 min |
| **Test** | Valider | `python Tests/test_sector_autoencoder_integration.py` | 2 min |

**Durée totale: 1-2 heures pour compléter ÉTAPE 1** ⏱️

---

**Version**: 1.0  
**Dernière mise à jour**: 25 Avril 2026  
**Status**: ✅ Prêt
