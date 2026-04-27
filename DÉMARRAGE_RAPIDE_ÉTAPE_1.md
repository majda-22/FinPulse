# 🎯 ÉTAPE 1: SECTOR AUTOENCODER - DÉMARRAGE RAPIDE

**📅 Date**: 25 Avril 2026  
**🟢 Status**: PRÊT POUR EXÉCUTION  
**⏱️ Durée**: 2-3 heures  
**📈 Complexité**: Moyen ⭐⭐⭐  

---

## ⚡ TL;DR - 30 secondes

```bash
# 1. Entraîner les modèles (45-60 min)
python train_autoencoder.py

# 2. Scorer les embeddings (60-120 min)
python score_embeddings.py --batch 100

# 3. Valider (2 min)
python Tests/test_sector_autoencoder_integration.py

# ✅ DONE! Tous les embeddings ont anomaly_score
```

**Résultat**: Tous les embeddings de votre BD ont maintenant:
- ✅ `reconstruction_error` (MSE)
- ✅ `anomaly_score` ∈ [0, 1]

---

## 📚 Fichiers Importants

| Fichier | Type | Objectif |
|---------|------|----------|
| `signals/sector_autoencoder.py` | 💻 Code | Module principal |
| `train_autoencoder.py` | 🎯 Script | PHASE 2: Entraîner |
| `score_embeddings.py` | 🎯 Script | PHASE 3: Scorer |
| `QUICK_REFERENCE_ÉTAPE_1.md` | 📖 Docs | Cheat sheet |
| `CHECKLIST_ÉTAPE_1.md` | ✅ Checklist | Step-by-step guide |

---

## 🚀 Exécution en 4 Étapes

### Étape 1: Préparation (5 min)

```bash
# Créer répertoire pour les modèles
mkdir -p data/autoencoder_models

# Vérifier les dépendances
python -c "
import torch, sqlalchemy
from app.db.session import SessionLocal
from app.db.models import Embedding

session = SessionLocal()
count = session.query(Embedding).count()
session.close()

print(f'✅ PyTorch: {torch.__version__}')
print(f'✅ Embeddings: {count}')
print('✅ Ready to start!')
"
```

**Résultat attendu**:
```
✅ PyTorch: 2.9.0
✅ Embeddings: 5000+
✅ Ready to start!
```

### Étape 2: Entraîner (45-60 min)

```bash
# Option A: Test rapide (1 secteur)
python train_autoencoder.py --sector 7372 --verbose

# Option B: Tous les secteurs (RECOMMENDED)
python train_autoencoder.py

# Option C: Secteurs spécifiques
python train_autoencoder.py --sector 7372 3721 2731
```

**Attendre**, puis vérifier:

```bash
ls -la data/autoencoder_models/
# Doit afficher: sector_XXXX.pt et sector_XXXX_threshold.pkl pour chaque secteur
```

### Étape 3: Scorer (60-120 min)

```bash
# Mode BATCH (RECOMMENDED - plus rapide)
python score_embeddings.py --batch 100

# Ou mode séquentiel
python score_embeddings.py
```

**Attendre**, puis vérifier:

```python
python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding
from sqlalchemy import func

s = SessionLocal()
scored = s.query(Embedding).filter(
    Embedding.anomaly_score.isnot(None)
).count()
total = s.query(Embedding).count()

print(f'Scored: {scored}/{total} ({100*scored/total:.1f}%)')
print('✅ DONE!' if scored == total else '⏳ Still running...')

s.close()
"
```

### Étape 4: Valider (2 min)

```bash
python Tests/test_sector_autoencoder_integration.py
```

**Résultat attendu**:
```
========================================================================
✅ ALL TESTS PASSED
========================================================================
```

---

## 🎯 Résultat Final Observable

### En Base de Données

```sql
-- AVANT ÉTAPE 1
SELECT COUNT(*) as embeddings_with_score
FROM embeddings 
WHERE anomaly_score IS NOT NULL;
-- Résultat: 0

-- APRÈS ÉTAPE 1
SELECT COUNT(*) as embeddings_with_score
FROM embeddings 
WHERE anomaly_score IS NOT NULL;
-- Résultat: 5000+ ✅
```

### Distribution des Scores

```sql
SELECT 
    COUNT(*) as total,
    MIN(anomaly_score) as min_score,
    MAX(anomaly_score) as max_score,
    AVG(anomaly_score) as avg_score
FROM embeddings 
WHERE anomaly_score IS NOT NULL;

-- Résultat attendu:
-- total | min_score | max_score | avg_score
-- 5000  | 0.0234    | 0.8756    | 0.3421
```

### Top Anomalies

```sql
SELECT 
    filing_id,
    anomaly_score,
    SUBSTRING(text, 1, 60) as preview
FROM embeddings 
WHERE anomaly_score IS NOT NULL
ORDER BY anomaly_score DESC 
LIMIT 10;

-- Tous les scores doivent être > 0.7 (anomalies fortes)
```

---

## ❓ Questions Fréquentes

### Q: Combien de temps ça prend?
**A**: 2-3 heures total:
- Entraînement: 45-60 min (dépend du nombre de secteurs)
- Scoring: 60-120 min (dépend du nombre de filings)
- Tests: 2-5 min

### Q: Je peux exécuter en parallèle?
**A**: Non. PHASE 2 avant PHASE 3:
1. ✅ Train dabord
2. ⏳ Puis score

### Q: Mon GPU/CPU est lent?
**A**: Utilisez batch mode:
```bash
python score_embeddings.py --batch 200  # Plus rapide
```

### Q: Ça peut échouer à mi-chemin?
**A**: Oui, mais c'est OK - relancer le script continuera depuis les filings non-scorés:
```bash
python score_embeddings.py --batch 100
# Relancer: continuera du dernier filings scoré
```

### Q: Comment je vois les modèles?
**A**: 
```bash
ls -lh data/autoencoder_models/
# Affiche tous les modèles entraînés
```

### Q: Comment je teste?"
**A**:
```bash
python Tests/test_sector_autoencoder_integration.py
```

---

## 📊 Ce Qui se Passe Techniquement

### Phase 2: Entraînement

```
Pour chaque secteur (Ex: Software 7372):
1. Charger 2847 embeddings (50 paragraphes × 57 filings)
2. Split 80/20: 2277 train, 570 validation
3. Créer autoencoder (1024→512→256→512→1024)
4. Entraîner 50 epochs:
   - Epoch 1: Loss = 0.512
   - Epoch 25: Loss = 0.0345
   - Epoch 50: Loss = 0.0189 ✅
5. Calculer seuil: 95e percentile du MSE d'entraînement = 0.0847
6. Sauvegarder: sector_7372.pt + threshold.pkl
```

### Phase 3: Scoring

```
Pour chaque filing (Ex: APPLE 10-Q):
1. Charger le modèle du secteur (7372 = Software)
2. Pour chaque embedding (100 paragraphes):
   a. Embedding (1024) → Modèle → Reconstruction (1024)
   b. MSE = mean((input - output)²) = 0.0089
   c. anomaly_score = min(1.0, MSE / threshold)
                    = min(1.0, 0.0089 / 0.0847)
                    = 0.105
   d. UPDATE: embeddings SET anomaly_score = 0.105
3. Commit à la BD
```

### Interprétation

```
anomaly_score ∈ [0, 1]:

0.00-0.10: ✅ NORMAL (embedding similar to sector)
0.10-0.40: ⚠️  SLIGHTLY UNUSUAL (but acceptable)
0.40-0.70: 🔶 UNUSUAL (attention requise)
0.70-1.00: 🚨 ANOMALOUS (à étudier)
```

---

## ⚠️ Points Critiques

### AVANT de démarrer

- [ ] **Embeddings**: Au moins 5000 en BD
- [ ] **Secteurs**: Au moins 5 (auto-détection)
- [ ] **PyTorch**: `2.9.0` installé
- [ ] **Répertoire**: `mkdir -p data/autoencoder_models`

### PENDANT exécution

- [ ] Ne pas arrêter les scripts brutalement (Ctrl+C ok)
- [ ] GPU/CPU: LaissLaissez du temps (~2-3h total)
- [ ] Pas de modifications BD en cours d'exécution

### APRÈS exécution

- [ ] Vérifier 100% embeddings scorés
- [ ] Vérifier stats: min<<avg<<max
- [ ] Tests doivent tous passer

---

## 📈 Performance Optimale

### Configuration Recommandée

```
CPU: ✅ OK (lent mais ok)
GPU: ⭐⭐⭐ 3-5x plus rapide

Batch size: 50-100 (bon équilibre vitesse/mémoire)
Epochs: 50 (bon pour convergence)
```

### Commandes Optimales

```bash
# RAPIDE (Batch)
python score_embeddings.py --batch 100

# TRÈS RAPIDE (Batch + GPU)
# (Automatique si GPU disponible)
python score_embeddings.py --batch 200

# LENT (Séquentiel)
python score_embeddings.py
```

---

## 🎯 Vérification Finale

```python
# Exécuter après ÉTAPE 1

python -c "
from app.db.session import SessionLocal
from app.db.models import Embedding, Filing
from sqlalchemy import func

s = SessionLocal()

print('🔍 ÉTAPE 1 VERIFICATION')
print('=' * 50)

# 1. Count
total = s.query(Embedding).count()
scored = s.query(Embedding).filter(
    Embedding.anomaly_score.isnot(None)
).count()

print(f'Total embeddings: {total}')
print(f'Scored embeddings: {scored}')
assert scored == total, f'❌ {total - scored} embeddings still NULL'
print(f'✅ 100% scored')

# 2. Stats
stats = s.query(
    func.min(Embedding.anomaly_score),
    func.max(Embedding.anomaly_score),
    func.avg(Embedding.anomaly_score),
).first()

print(f'\nScore distribution:')
print(f'  Min: {stats[0]:.4f}')
print(f'  Max: {stats[1]:.4f}')
print(f'  Avg: {stats[2]:.4f}')
assert stats[0] > 0 and stats[1] < 1, '❌ Invalid scores'
print(f'✅ Valid range [0, 1]')

# 3. Filing flags
unscored = s.query(Filing).filter(
    Filing.is_anomaly_scored == False
).count()

print(f'\nFiling flags:')
print(f'  Unscored filings: {unscored}')
assert unscored == 0, f'❌ {unscored} filings not marked'
print(f'✅ All flags updated')

print('\n' + '=' * 50)
print('✅ ÉTAPE 1 COMPLETED SUCCESSFULLY!')

s.close()
"
```

---

## 🚦 Status Indicators

### Vert ✅ (Ready)
- All embeddings scored
- All tests passing
- Next phase: ÉTAPE 2 ready

### Jaune ⚠️ (In Progress)
- Scoring in progress
- Some embeddings have NULL
- Be patient, let it finish

### Rouge 🔴 (Error)
- Tests failing
- Unexpected NULL values
- See QUICK_REFERENCE_ÉTAPE_1.md troubleshooting

---

## 📝 Prochaines Étapes

✅ **ÉTAPE 1** (MAINTENANT): Autoencoder
- Files: `train_autoencoder.py`, `score_embeddings.py`
- Durée: 2-3 heures
- Status: 🟢 PRÊT

⏳ **ÉTAPE 2** (APRÈS ÉTAPE 1): Composite Signals
- File: `signals/composite_engine.py` (à modifier)
- Triplet Convergence (RLDS+GCE+ITA)
- Durée: 2 heures

⏳ **ÉTAPE 3**: Quality Monitoring
- File: `signals/sentinel.py` (à créer)
- Freshness, insider sales, alerts
- Durée: 1.5 heures

⏳ **ÉTAPE 4**: LLM Explicability
- File: `signals/explainability_client.py` (à créer)
- Human-readable explanations
- Durée: 2 heures

---

## 💾 Fichiers Créés: Résumé

```
✅ signals/sector_autoencoder.py           (Core implementation)
✅ train_autoencoder.py                    (PHASE 2 script)
✅ score_embeddings.py                     (PHASE 3 script)
✅ Tests/test_sector_autoencoder_integration.py  (Validation)

✅ QUICK_REFERENCE_ÉTAPE_1.md              (Cheat sheet)
✅ ÉTAPE_1_AUTOENCODER_EXECUTION_GUIDE.md  (Full guide)
✅ ÉTAPE_1_ARCHITECTURE_FLUX.md            (Diagrams)
✅ ÉTAPE_1_INTEGRATION_PIPELINE.md         (Integration)
✅ CHECKLIST_ÉTAPE_1.md                    (Checklist)
✅ DÉMARRAGE_RAPIDE.md                     (This file)
```

---

## 🎯 C'est Parti!

### Copy-Paste this to start:

```bash
# Terminal 1: TRAIN
python train_autoencoder.py

# In parallel, Terminal 2 (after ~1 min training started):
# Watch progress
watch -n 5 'ls -la data/autoencoder_models/ | wc -l'

# After TRAIN completes:
# Terminal 3: SCORE
python score_embeddings.py --batch 100

# After SCORE completes:
# Terminal 4: VALIDATE
python Tests/test_sector_autoencoder_integration.py
```

---

**🟢 Status**: READY  
**⏱️ Estimated**: 2-3 hours  
**📊 Impact**: 100% embeddings will have anomaly_score ✅  

**Bonne chance!** 🚀

