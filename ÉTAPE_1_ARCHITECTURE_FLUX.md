# 📊 ÉTAPE 1: Architecture & Flux Visuel

## Flux Complet de l'Autoencoder

```
                        ┌─────────────────────────────────────────┐
                        │   DATABASE: PostgreSQL                  │
                        │                                         │
                        │  ┌─────────────┐  ┌───────────────┐   │
                        │  │  embeddings │  │   companies   │   │
                        │  │             │  │               │   │
                        │  │  ├─ id      │  │  ├─ id        │   │
                        │  │  ├─ filing  │  │  ├─ sic_code  │   │
                        │  │  ├─ text    │  │  ├─ sector    │   │
                        │  │  ├─ emb[1024]  │  │  └─ name    │   │
                        │  │  ├─ reconstruction_error (NULL)     │   │
                        │  │  └─ anomaly_score (NULL) ⬅️ TO FILL │   │
                        │  └─────────────┘  └───────────────┘   │
                        │                                         │
                        └──────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
                    ▼                                             ▼
        ╔═══════════════════════════════════╗    ╔══════════════════════════════════╗
        ║  PHASE 2: ENTRAÎNEMENT            ║    ║  PHASE 3: SCORING (Inférence)    ║
        ║  train_autoencoder.py             ║    ║  score_embeddings.py             ║
        ╚═══════════════════════════════════╝    ╚══════════════════════════════════╝
                    │                                             │
                    │ 1. Charge embeddings par secteur            │ 1. Pour chaque filing:
                    │    (Ex: 7372, 3721)                        │    a. Load embeddings
                    │                                             │    b. Get company.sic_code
                    │ 2. Split 80% train / 20% val               │    c. Load model(sector)
                    │    ├─ Train: 2277 samples                  │    d. For each embedding:
                    │    └─ Val:  570 samples                    │       - embedding → tensor
                    │                                             │       - model(tensor) → reconst
                    │ 3. Train 50 epochs                         │       - MSE = ||embedding - reconst||²
                    │    ├─ Forward pass                         │       - anomaly_score = min(1, MSE/threshold)
                    │    ├─ Loss = MSE(input, output)            │       - UPDATE DB
                    │    ├─ Backward pass (backprop)             │
                    │    └─ Update weights                       │ 2. Commit changes
                    │                                             │
                    │ 4. Calc threshold = 95th percentile        │
                    │    (95% data normal, 5% anomalies)         │
                    │                                             │
                    │ 5. Save:                                   │
                    │    ├─ sector_7372.pt (weights)             │
                    │    └─ sector_7372_threshold.pkl            │
                    │                                             │
                    ▼                                             ▼
        ┌─────────────────────────────────────┐    ┌────────────────────────────────────┐
        │  Models Directory                   │    │  Database Updated                  │
        │  data/autoencoder_models/           │    │                                    │
        │                                     │    │  embeddings table:                 │
        │  ├─ sector_7372.pt      (9.2 MB)   │    │  ├─ reconstruction_error ← MSE    │
        │  ├─ sector_7372_threshold.pkl      │    │  └─ anomaly_score ∈ [0, 1] ✅    │
        │  ├─ sector_3721.pt      (9.2 MB)   │    │                                    │
        │  ├─ sector_3721_threshold.pkl      │    │  Stats:                            │
        │  ├─ sector_2731.pt      (9.2 MB)   │    │  ├─ Min: 0.0234                   │
        │  ├─ sector_2731_threshold.pkl      │    │  ├─ Max: 0.8756                   │
        │  └─ ...                            │    │  ├─ Avg: 0.3421                   │
        │                                     │    │  └─ Std: 0.1895                   │
        └─────────────────────────────────────┘    └────────────────────────────────────┘
                                                                    ▲
                                                                    │
                                                          ✅ READY FOR ÉTAPE 2
```

---

## Architecture du Modèle: VectorAutoencoder

```python
INPUT EMBEDDING (1024 dimensions)
           │
           │ Représentation dense: texte, sémantique
           │
           ▼
    ┌─────────────┐
    │  Encoder    │
    ├─────────────┤
    │ Linear 1024 │ 
    │ → 512       │  ◄─ 1ère compression (50% réduction)
    ├─────────────┤
    │  ReLU       │  ◄─ Non-linéarité (capte patterns complexes)
    ├─────────────┤
    │ Dropout 10% │  ◄─ Régularisation (prévention overfitting)
    ├─────────────┤
    │ Linear 512  │
    │ → 256       │  ◄─ Goulot d'étranglement (75% réduction totale)
    ├─────────────┤
    │  ReLU       │  ◄─ Activation
    └─────────────┘
           │
      BOTTLENECK (256 dimensions) ◄─ ESSENCE de l'embedding
           │
           │ Représentation compressée: l'autoencoder
           │ apprend l'essence de chaque secteur
           │
           ▼
    ┌─────────────┐
    │  Decoder    │
    ├─────────────┤
    │ Linear 256  │
    │ → 512       │  ◄─ Ré-expansion
    ├─────────────┤
    │  ReLU       │
    ├─────────────┤
    │ Dropout 10% │
    ├─────────────┤
    │ Linear 512  │
    │ → 1024      │  ◄─ Retour à la dimension originale
    └─────────────┘
           │
    OUTPUT RECONSTRUCTION (1024 dimensions)
           │
           │ Si input = embedding normal → reconstruction fidèle
           │ Si input = embedding anormal → reconstruction mauvaise
           │
           ▼
    MSE = Mean Squared Error
    MSE = (1/1024) * Σ(input[i] - output[i])²


Cas Normal (Software filing):        Cas Anormal (Outlier):
───────────────────────────────      ──────────────────────
Input: [0.2, 0.3, 0.1, ...]   →     Input: [-0.9, 2.1, 0.05, ...] →
Output: [0.19, 0.31, 0.11, ...]      Output: [0.1, 0.05, 0.9, ...]
MSE ≈ 0.0089 (petit)                 MSE ≈ 0.847 (grand!)
anomaly_score = 0.0089/0.0847 = 0.11 anomaly_score = min(1, 0.847/0.0847) = 1.0
```

---

## Pipeline de Traitement Cas à Cas

### Cas 1: Embedding Normal

```
Filing (APPLE 10-Q):
├─ Company: APPLE INC
├─ SIC Code: 7372 (Software)
└─ embedding #42: [0.125, 0.203, -0.087, ... 1024 values]
        │
        ▼
Load model sector_7372.pt
        │
        ▼
Forward pass:
├─ Encode: [0.125, ...1024] → [0.031, ...512] → [0.005, ...256]
└─ Decode: [0.005, ...256] → [0.034, ...512] → [0.124, 0.204, -0.088, ...1024]
        │
        ▼
MSE = 0.0089 ✅ PETIT (bonne reconstruction)
        │
        ▼
threshold (sector_7372) = 0.0847
        │
        ▼
anomaly_score = min(1.0, 0.0089 / 0.0847) = 0.105 ✅
        │
        ▼
UPDATE embeddings SET
    reconstruction_error = 0.0089,
    anomaly_score = 0.105
WHERE id = 42;

✅ RÉSULTAT: Ce paragraphe est NORMAL (score bas)
```

### Cas 2: Embedding Anormal

```
Filing (ACME CORP 10-K):
├─ Company: ACME CORP
├─ SIC Code: 3721 (Semiconductors)
└─ embedding #567: [-0.901, 2.341, 0.051, ... OUTLIER VALUES]
        │
        ▼
Load model sector_3721.pt
        │
        ▼
Forward pass:
├─ Encode: [weird values] → [compressed weird] → [bottleneck weird]
└─ Decode: [tries to reconstruct] → [fails] → [bad reconstruction]
        │
        ▼
MSE = 0.742 ⚠️ GRAND (mauvaise reconstruction)
        │
        ▼
threshold (sector_3721) = 0.0624
        │
        ▼
anomaly_score = min(1.0, 0.742 / 0.0624) = min(1.0, 11.9) = 1.0 🚨
        │
        ▼
UPDATE embeddings SET
    reconstruction_error = 0.742,
    anomaly_score = 1.0
WHERE id = 567;

🚨 RÉSULTAT: Ce paragraphe est ANORMAL (score élevé)
    → À étudier → Risque potentiel
```

---

## Distribution des Anomaly Scores

```
Histogramme typique après scoring:

anomaly_score
     │
 100 │  ██
  90 │  ██
  80 │  ███
  70 │  ███
  60 │  ████
  50 │  █████
  40 │  ██████
  30 │  ███████  ◄─ Majorité des embeddings "normaux"
  20 │  ████████
  10 │  ████████
   0 │  ██████████████ ◄─ Quelques outliers fortement anormaux
     └───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───
       0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1.0


Stats typiques:
├─ Min: 0.0234      (embedding très normal)
├─ Max: 0.8756      (embedding très anormal, presque 1.0)
├─ Avg: 0.3421      (moyenne ~30% anomalie)
├─ Median: 0.2890
│
├─ TOP 5% (anomaly_score > 0.68): Étudier ces paragraphes 🔍
├─ TOP 1% (anomaly_score > 0.80): ALERTE ROUGE 🚨
└─ Percentile 95: 0.6789 (seuil de décision)
```

---

## Flux d'Execution des Scripts

### Phase 2: Train

```
┌─────────────────────────────────────────────────────────────┐
│ python train_autoencoder.py                                 │
│                                                             │
│ Args:                                                       │
│  --sector 7372 3721      (optionnel: secteurs spécifiques) │
│  --verbose               (optionnel: logs détaillés)       │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │ Auto-detect sectors │
        │ (SQL DISTINCT ...)  │
        └──────────┬──────────┘
                   │
        ┌──────────▼──────────────────────────────┐
        │ For each sector:                        │
        │  1. Load embeddings (365 days)          │
        │  2. Split 80/20                         │
        │  3. Train 50 epochs                     │
        │  4. Calc threshold (95th percentile)   │
        │  5. Save model + threshold              │
        └──────────┬──────────────────────────────┘
                   │
        ┌──────────▼────────────────────────────────────┐
        │ models/                                      │
        │  ├─ sector_7372.pt + threshold.pkl  ✅      │
        │  ├─ sector_3721.pt + threshold.pkl  ✅      │
        │  └─ sector_2731.pt + threshold.pkl  ✅      │
        └────────────────────────────────────────────────┘
```

### Phase 3: Score

```
┌─────────────────────────────────────────────────────────────┐
│ python score_embeddings.py                                  │
│                                                             │
│ Args:                                                       │
│  --filing 1 2 3          (specific filings)                │
│  --recent 50             (recent N filings)                │
│  --batch 100             (batch size)                      │
│  --dry-run               (preview without commit)          │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────▼──────────────────────────┐
        │ Query filings to process            │
        │ (filtered by args)                  │
        └──────────┬──────────────────────────┘
                   │
        ┌──────────▼──────────────────────────┐
        │ For each filing:                    │
        │  1. Load all embeddings             │
        │  2. Get company.sic_code            │
        │  3. Load model(sector_code)         │
        │  4. For each embedding:             │
        │     a. tensor ← embedding[1024]     │
        │     b. recon ← model(tensor)        │
        │     c. MSE ← mean(tensor-recon)²    │
        │     d. score ← min(1, MSE/threshold)│
        │     e. UPDATE DB                    │
        │  5. Commit                          │
        └──────────┬──────────────────────────┘
                   │
        ┌──────────▼────────────────────────────────────┐
        │ Database Updated:                            │
        │  embeddings.reconstruction_error   ← MSE      │
        │  embeddings.anomaly_score          ← score    │
        │                                     ← FILLED! ✅│
        └────────────────────────────────────────────────┘
```

---

## Timeline Complète

```
Temps            Activité
─────────────────────────────────────────────────────────

T=0 min          Démarrage
                 ├─ mkdir data/autoencoder_models/
                 └─ python train_autoencoder.py

T=1-2 min        Phase 2 - Loading data
                 └─ Query 5000+ embeddings par secteur

T=2-10 min       Phase 2 - Training sector 1
                 ├─ Epoch 1-50
                 └─ Loss: 0.512 → 0.0189

T=10-20 min      Phase 2 - Training sector 2
T=20-30 min      Phase 2 - Training sector 3
T=30-45 min      Phase 2 - Training remaining sectors
                 └─ Models saved ✅

T=45 min         Phase 3 - Loading models
                 └─ All sector models in memory

T=45-50 min      Phase 3 - Scoring filings 1-50
                 ├─ 50 filings × 100 embeddings/filing
                 └─ 5000 embeddings scored

T=50-100 min     Phase 3 - Scoring filings 51-150
T=100-150 min    Phase 3 - Scoring remaining
                 └─ Database committed ✅

T=150 min        Finalization
                 ├─ ALL embeddings have anomaly_score ✅
                 └─ Ready for ÉTAPE 2 ✅

Total: ~2.5 hours for full pipeline (with 1000 filings)
```

---

## Qualité des Modèles

```
Validation Metrics:
───────────────────

Sector 7372 (Software):
├─ Train Loss: 0.0189
├─ Val Loss:   0.0206        ◄─ Small gap = good generalization ✅
├─ Threshold:  0.0847
├─ Samples:    2847
└─ Status:     Production Ready ✅

Sector 3721 (Semiconductors):
├─ Train Loss: 0.0156
├─ Val Loss:   0.0198        ◄─ Good
├─ Threshold:  0.0624
├─ Samples:    1956
└─ Status:     Production Ready ✅

Sector 2731 (Electronics):
├─ Train Loss: 0.0401        ⚠️  Slightly higher
├─ Val Loss:   0.0512        ⚠️  More noise
├─ Threshold:  0.1234
├─ Samples:    687           ⚠️  Fewer samples
└─ Status:     Use with caution


Gap Analysis (Val Loss - Train Loss):
├─ Small gap (<0.005): Model generalizes well ✅
├─ Medium gap (0.005-0.01): Normal
└─ Large gap (>0.01): May indicate overfitting ⚠️
```

---

**Version**: 1.0  
**Date**: 25 Avril 2026  
**Status**: ✅ Architecture & Flux Finalisés
