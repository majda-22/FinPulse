# 📋 Plan d'Implémentation Détaillé — FinPulse 4 Responsabilités

**Date**: Avril 24, 2026  
**Statut**: Plan Initial  
**Auteur**: Équipe Technique  

---

## 📑 Table des Matières

1. [Vue d'ensemble du contexte](#vue-densemble)
2. [Architecture Générale](#architecture)
3. [Responsabilité 1: Sector Autoencoder](#responsabilité-1--sector-autoencoder)
4. [Responsabilité 2: Convergence Signal](#responsabilité-2--signal-de-convergence)
5. [Responsabilité 3: Sentinel - Qua2lity Monitoring](#responsabilité-3--sentinel)
6. [Responsabilité 4: LLM Explicability](#responsabilité-4--explicabilité-llm)
7. [Intégration Globale](#intégration-globale)
8. [Roadmap d'Implémentation](#roadmap)
9. [Dépannage & Support](#dépannage)

---

## Vue d'ensemble

### 🎯 Objectif Global

Vous devez développer une **couche d'analyse intermédiaire** entre les signaux bruts et l'API finale. Cette couche enrichit les scores de risque NCI avec :

- **Détection d'anomalies** (embeddings via autoencoder)
- **Convergence multi-signaux** (triplet RLDS+GCE+ITA)
- **Contrôle de qualité** (fraîcheur, alertes, delta scores)
- **Narration LLM** (explications humaines des résultats)

### 📊 Pipeline Existant vs Nouveau

```
┌─────────────────────────────────────────────────────────────────┐
│ INGESTION & PROCESSING (Déjà existe)                           │
│ Filing → Embeddings (1024-dim) + Signals (text,numeric,etc)    │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ ⭐ VOTRE COUCHE (À CRÉER) ⭐                                   │
│                                                                 │
│ 1️⃣ Autoencoder        → reconstruction_error, anomaly_score   │
│ 2️⃣ Triplet Convergence → triplet_boost (RLDS+GCE+ITA)         │
│ 3️⃣ Sentinel           → quality_alerts, freshness checks      │
│ 4️⃣ LLM Explicability  → narrative, severity, actionability    │
└────────────────────────┬────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│ API / ALERTES (Consomme vos résultats)                         │
│ GET /api/nci/{filing_id} → Score + Explications + Alertes     │
└─────────────────────────────────────────────────────────────────┘
```

### 🗂️ Fichiers que Vous Allez Créer/Modifier

| Responsabilité | Fichier | Type | État |
|---|---|---|---|
| **1. Autoencoder** | `signals/sector_autoencoder.py` | CRÉER | ⬜ TODO |
| **2. Convergence** | `signals/composite_engine.py` | MODIFIER | ⬜ TODO |
| **3. Sentinel** | `signals/sentinel.py` | CRÉER | ⬜ TODO |
| **4. Explicability** | `signals/explainability_client.py` | CRÉER | ⬜ TODO |

---

## Architecture

### 🔄 Flux de Données Complet

```
ÉTAPE 0: Ingestion & Embeddings (Déjà existe)
    Filing 10-Q/10-K
    ↓
    extract XBRL, text sections
    ↓
    chunk paragraphs (500-word chunks)
    ↓
    generate embeddings: 1024-dim vectors via Mistral model
    ↓
    STORE → embeddings table (avec colonnes vides: reconstruction_error, anomaly_score)

ÉTAPE 1: Votre Autoencoder (À faire)
    embeddings table
    ↓
    sector_autoencoder.compute_embeddings_anomaly_scores(filing_id)
    ├─ Load sector-specific trained model
    ├─ Compute MSE (Mean Squared Error) du reconstruction
    ├─ Normalize MSE → anomaly_score ∈ [0, 1]
    └─ UPDATE → embeddings.reconstruction_error, anomaly_score
    ↓
    Result: Chaque paragraphe a un anomaly_score

ÉTAPE 2: Composite Signals Améliorés (À faire)
    signal_scores table (text, numeric, behavior, market, sentiment)
    ↓
    composite_engine.compute_composite_signals()
    ├─ existing: convergence_signal (5 couches)
    ├─ NEW: triplet_convergence_signal (RLDS+GCE+ITA)
    ├─ existing: nci_global (score composite)
    └─ existing: divergence_signal (text vs numeric)
    ↓
    Result: Nouvelle métrique triplet_boost ∈ [0, 0.25]

ÉTAPE 3: Quality Monitoring (À faire)
    nci_scores table
    ↓
    sentinel.evaluate_filing_quality(filing_id)
    ├─ Check freshness (90d 10-Q, 365d 10-K)
    ├─ Detect unplanned insider sales (Form 4)
    ├─ Compute NCI delta vs previous quarter
    └─ Generate alerts (freshness, sales, nci_delta)
    ↓
    Result: Quality alerts stored + logged

ÉTAPE 4: LLM Explanations (À faire)
    nci_scores.top_anomalous_paragraphs (déjà peuplé)
    ↓
    explainability_client.load_and_explain_nci_score()
    ├─ Format paragraphs anormaux + context
    ├─ Call Spring AI service (Java backend) via HTTP
    ├─ Parse LLM response
    └─ Store narrative + severity + actionability
    ↓
    Result: Human-readable explanation + risks

FINAL API
    GET /api/nci/{filing_id}
    ↓
    Returns:
    {
      nci_global: 0.68,
      triplet_convergence: 0.25,
      triplet_confidence: "full",
      data_fresh: true,
      quality_alerts: [...],
      llm_narrative: "...",
      severity_level: "high",
      actionability: "urgent"
    }
```

---

# Responsabilité 1 → Sector Autoencoder

## 🎯 Objectif

Créer un système qui détecte automatiquement les **paragraphes anomalous** dans les documents financiers en comparant leurs embeddings à un modèle de reconstruction.

**Métaphore**: Comme un "détecteur de fraude" — si la reconstruction d'un vecteur requiert beaucoup d'énergie (MSE élevé), c'est qu'il est anormal.

---

## 📚 Contexte Existant

### Données Disponibles

**Table: `embeddings`**
```sql
SELECT 
    id,
    filing_id,
    company_id,
    chunk_idx,
    text,                    -- Paragraph text
    embedding,               -- 1024-dim vector (Mistral model)
    provider,                -- "mistral", "openai", etc
    embedding_model,         -- "mistral-embed", etc
    reconstruction_error,    -- ⬜ NULL (à remplir)
    anomaly_score,           -- ⬜ NULL (à remplir)
    created_at
FROM embeddings;
```

**Métadonnées Company:**
```sql
SELECT 
    id,
    name,
    sic_code,  -- Industry classification (ex: "7372" = Software)
    ...
FROM companies;
```

**Approche Existante:**
- Les embeddings sont générés par le modèle Mistral (1024 dimensions)
- Chaque embedding représente un paragraphe unique
- Pas de normalisation cross-sector actuellement

### Concept: Autoencoder

L'autoencoder apprend à **reconstruire** les embeddings "sains" d'une industrie. Quand on lui montre un embedding anormal, il aura du mal à le reconstruire correctement → **MSE élevé = anomalie**.

**Architecture Simple:**
```
Input (1024 dims)
    ↓
Hidden Layer 1 (512 dims)  ← Compression
    ↓
Bottleneck (256 dims)      ← Goulot d'étranglement
    ↓
Hidden Layer 2 (512 dims)  ← Expansion
    ↓
Output (1024 dims)         ← Reconstruction
    ↓
Loss = MSE(Input, Output)  ← Plus élevé = plus anormal
```

---

## 🛠️ Étape 1.1: Conception du Modèle

### Fichier à Créer: `signals/sector_autoencoder.py`

**Structure du fichier:**

```python
# 1. IMPORTS & CONFIGURATION
import torch
import torch.nn as nn
import numpy as np
from sqlalchemy import select
from datetime import datetime

# Configuration hyperparamètres
AUTOENCODER_HIDDEN_SIZE = 512       # Première couche cachée
AUTOENCODER_BOTTLENECK_SIZE = 256   # Goulot d'étranglement
AUTOENCODER_LEARNING_RATE = 0.001   # Vitesse d'apprentissage
AUTOENCODER_EPOCHS = 50             # Cycles d'entraînement
AUTOENCODER_BATCH_SIZE = 32         # Taille des batches
AUTOENCODER_ANOMALY_THRESHOLD_PERCENTILE = 95  # 95% des données normales

# 2. CLASSE MODÈLE
class VectorAutoencoder(nn.Module):
    """Autoencoder symétrique pour vectores 1024-dim"""
    def __init__(self, input_dim: int = 1024):
        super().__init__()
        # Encodeur
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, AUTOENCODER_HIDDEN_SIZE),
            nn.ReLU(),
            nn.Linear(AUTOENCODER_HIDDEN_SIZE, AUTOENCODER_BOTTLENECK_SIZE),
            nn.ReLU(),
        )
        # Décodeur (symétrique)
        self.decoder = nn.Sequential(
            nn.Linear(AUTOENCODER_BOTTLENECK_SIZE, AUTOENCODER_HIDDEN_SIZE),
            nn.ReLU(),
            nn.Linear(AUTOENCODER_HIDDEN_SIZE, input_dim),
        )
    
    def forward(self, x):
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded

# 3. FUNCTIONS PRINCIPALES
def train_sector_autoencoders(...):
    """Entraîner des autoencoders pour chaque secteur industiel"""
    pass

def compute_embeddings_anomaly_scores(...):
    """Calculer MSE pour les embeddings récents"""
    pass
```

### Explications Clés

1. **Pourquoi PyTorch?**
   - Déjà dans `requirements.txt` (`torch==2.9.0`)
   - Flexible pour training + inference
   - GPU-compatible si besoin

2. **Architecture Symétrique?**
   - Entrée: 1024 → Compression: 512 → Bottleneck: 256
   - Sortie: Bottleneck: 256 → Expansion: 512 → 1024
   - Apprend une **représentation compressée** puis la **reconstruit**

3. **Threshold (95th percentile)?**
   - Collecte MSE des données d'entraînement "clean"
   - Le 95e percentile = seuil de normalité
   - Au-delà = anomalies (5% supérieur)

---

## 🔄 Étape 1.2: Entraînement du Modèle

### Phase 1: Préparer les Données

**Pseudocode:**
```python
def train_sector_autoencoders(sector_codes=["7372", "3721"], lookback_is_recent=True):
    
    # ÉTAPE 1: Charger les embeddings par secteur
    for sector_code in sector_codes:
        embeddings = db.query(
            Embedding.embedding  # 1024-dim vector
        ).join(Filing).join(Company).filter(
            Company.sic_code == sector_code,
            Embedding.created_at > NOW() - 365 days  # Données récentes
        ).all()
        
        # Minimum 100 samples pour entraîner
        if len(embeddings) < 100:
            print(f"Sector {sector_code}: insufficient data, skipping")
            continue
        
        embeddings_array = np.array(embeddings)  # Shape: (N, 1024)
        
        # ÉTAPE 2: Diviser train/val
        split_idx = int(0.8 * len(embeddings_array))
        train_data = embeddings_array[:split_idx]
        val_data = embeddings_array[split_idx:]
        
        # ÉTAPE 3: Entraîner le modèle
        model = VectorAutoencoder()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
        criterion = nn.MSELoss()
        
        for epoch in range(50):
            # Training loop
            for batch in train_data:
                output = model(batch)
                loss = criterion(output, batch)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            
            # Validation
            with torch.no_grad():
                val_output = model(val_data)
                val_loss = criterion(val_output, val_data)
        
        # ÉTAPE 4: Calculer le seuil d'anomalie
        with torch.no_grad():
            train_mse = MSE(model(train_data), train_data)
            threshold = np.percentile(train_mse, 95)  # 95e percentile
        
        # ÉTAPE 5: Sauvegarder le modèle
        torch.save(model.state_dict(), f"models/sector_{sector_code}.pt")
        # TODO: Aussi sauvegarder threshold en DB

print("✅ Entraînement terminé")
```

### Résultats Attendus

```
INFO: Sector 7372 (Software): Trained 2847 samples
  - Train loss: 0.0234
  - Val loss: 0.0251
  - Anomaly threshold (95th percentile): 0.0847

INFO: Sector 3721 (Semiconductors): Trained 1956 samples
  - Train loss: 0.0189
  - Val loss: 0.0206
  - Anomaly threshold (95th percentile): 0.0624

✅ Models saved to data/autoencoder_models/
```

---

## 📊 Étape 1.3: Inférence (Scoring)

### Phase 2: Scorer les Embeddings Récents

**Fonction: `compute_embeddings_anomaly_scores(filing_id)`**

```python
def compute_embeddings_anomaly_scores(filing_id: int):
    
    # ÉTAPE 1: Charger les embeddings du filing
    embeddings_list = db.query(Embedding).filter(
        Embedding.filing_id == filing_id
    ).all()  # Ex: 100 paragraphes
    
    # ÉTAPE 2: Pour chaque embedding, obtenir le secteur de la company
    for embedding in embeddings_list:
        filing = db.query(Filing).get(embedding.filing_id)
        sector_code = filing.company.sic_code
        
        # ÉTAPE 3: Charger le modèle du secteur
        model_state = torch.load(f"models/sector_{sector_code}.pt")
        model = VectorAutoencoder()
        model.load_state_dict(model_state)
        model.eval()
        
        # ÉTAPE 4: Calculer MSE (reconstruction error)
        embedding_vector = np.array(embedding.embedding)  # 1024-dim
        embedding_tensor = torch.FloatTensor([embedding_vector])
        
        with torch.no_grad():
            reconstructed = model(embedding_tensor)
            mse = np.mean((embedding_vector - reconstructed.numpy()) ** 2)
        
        # ÉTAPE 5: Normaliser le MSE en score d'anomalie [0, 1]
        threshold = THRESHOLDS[sector_code]  # Ex: 0.0847
        anomaly_score = min(mse / threshold, 1.0)  # Clamp à [0, 1]
        
        # ÉTAPE 6: Mettre à jour la DB
        db.execute(
            UPDATE(Embedding)
            .where(Embedding.id == embedding.id)
            .values(
                reconstruction_error=float(mse),
                anomaly_score=float(anomaly_score)
            )
        )
        db.commit()

print(f"✅ Scored {len(embeddings_list)} embeddings")
print(f"   High anomalies (>0.7): {count_high}")
```

### Résultats Attendus

```
Filing ID: 12345
  - Total paragraphs: 87
  - Processed: 87
  - Anomalies detected (>0.70): 12
  
  Sample results:
    Paragraph 3: MSE=0.0812, anomaly_score=0.96 ⚠️ ANOMALOUS
    Paragraph 5: MSE=0.0234, anomaly_score=0.28 ✅ Normal
    Paragraph 41: MSE=0.0756, anomaly_score=0.89 ⚠️ ANOMALOUS
```

---

## 💾 Étape 1.4: Stockage & Métadonnées

### Créer Table de Métadonnées

**SQL à exécuter:**
```sql
CREATE TABLE sector_autoencoder_models (
    id SERIAL PRIMARY KEY,
    sector_code VARCHAR(10) NOT NULL,
    model_path VARCHAR(500),
    anomaly_threshold FLOAT,
    num_training_samples INT,
    train_loss FLOAT,
    val_loss FLOAT,
    trained_at TIMESTAMP DEFAULT NOW(),
    model_version VARCHAR(50),
    UNIQUE(sector_code, model_version)
);

-- Index pour recherches rapides
CREATE INDEX idx_sector_code ON sector_autoencoder_models(sector_code);
```

### Insérer Métadonnées Après Entraînement

```python
def _save_sector_model_metadata(sector_code, metrics):
    db.execute(INSERT(SectorAutoencoderModels).values(
        sector_code=sector_code,
        model_path=f"data/autoencoder_models/sector_{sector_code}.pt",
        anomaly_threshold=metrics.anomaly_threshold,
        num_training_samples=metrics.num_samples,
        train_loss=metrics.train_loss,
        val_loss=metrics.val_loss,
        model_version="v1"
    ))
    db.commit()
```

---

## ✅ Étape 1.5: Checkliste Autoencoder

```
CONCEPTION:
  ☐ Créer classe VectorAutoencoder dans sector_autoencoder.py
  ☐ Définir hyperparamètres (hidden_size, bottleneck, epochs, etc)
  ☐ Valider architecture (1024 → 512 → 256 → 512 → 1024)

ENTRAÎNEMENT:
  ☐ Implémenter train_sector_autoencoders()
  ☐ Charger embeddings par secteur depuis DB
  ☐ 80/20 split train/validation
  ☐ Training loop avec Adam optimizer
  ☐ Calculer anomaly_threshold (95th percentile)
  ☐ Sauvegarder modèles dans data/autoencoder_models/

INFÉRENCE:
  ☐ Implémenter compute_embeddings_anomaly_scores()
  ☐ Charger modèles depuis disque
  ☐ Calculer MSE pour embeddings récents
  ☐ Normaliser MSE → anomaly_score [0, 1]
  ☐ UPDATE embeddings table

MÉTADONNÉES:
  ☐ Créer table sector_autoencoder_models
  ☐ Sauvegarder métriques d'entraînement
  ☐ Tracker versions de modèles

TESTS:
  ☐ Vérifier que anomaly_score ∈ [0, 1]
  ☐ Vérifier que ~95% des données <= 0.75
  ☐ Comparer anomaly_score avec RLDS signal (doivent corréler)
  ☐ Benchmark: temps de scoring pour 1000 embeddings
```

---

# Responsabilité 2 → Signal de Convergence

## 🎯 Objectif

Créer un **signal de convergence cible** qui surveille spécifiquement 3 signaux clés :

1. **RLDS** (Text Anomaly) — Détection d'anomalies textuelles
2. **GCE** (aka `forward_pessimism`) — Sentiment pessimiste des prospectives
3. **ITA** (aka `insider_signal`) — Anomalies dans transactions insider

**Logique**: Quand ces 3 signaux sont tous élevés simultanément → **SIGNAL TRÈS FORT** de risque.

---

## 📚 Contexte Existant

### Signaux Disponibles dans `signal_scores` Table

```sql
SELECT 
    id,
    filing_id,
    company_id,
    signal_name,        -- Ex: "rlds", "forward_pessimism", "insider_signal"
    signal_value,       -- Score ∈ [0, 1]
    detail,             -- JSON avec metadata
    computed_at
FROM signal_scores
WHERE signal_name IN ('rlds', 'forward_pessimism', 'insider_signal');
```

### Signaux Existants dans Composite Engine

**Fonction: `compute_composite_signals(filing_id)`**

Actuellement retourne 4 signaux:
1. `narrative_numeric_divergence` — Divergence text vs numeric
2. `convergence_signal` — Convergence des 5 couches (text, numeric, behavior, market, sentiment)
3. `nci_global` — Score NCI composite
4. `composite_filing_risk` — Alias du NCI

**Vous allez ajouter:**
5. `triplet_convergence_signal` — Convergence (RLDS + GCE + ITA) ← **NEW**

---

## 🔄 Étape 2.1: Comprendre les Signaux en Input

### Signal 1: RLDS (Relative Linear Drift Score)

**Source**: `signals/text_signals.py`

**Meaning**: Mesure la **nouveauté/anomalie du texte** par rapport à l'historique.
- Valeur élevée (ex: 0.70) = Le texte est très différent des précédentes périodes
- Valeur basse (ex: 0.15) = Le texte est similaire à l'historique

**Seuil de vigilance**: RLDS > 0.25 = "Élevé"

### Signal 2: GCE (aka `forward_pessimism`)

**Source**: `signals/text_signals.py`

**Meaning**: Sentiment **pessimiste des prospectives** (forward guidance).
- Compte les mots négatifs dans la section Outlook/Guidance
- Valeur élevée = Beaucoup de langage pessimiste
- Valeur basse = Langage neutre/optimiste

**Seuil de vigilance**: forward_pessimism > 0.25 = "Élevé"

### Signal 3: ITA (aka `insider_signal`)

**Source**: `signals/insider_signals.py`

**Meaning**: Anomalies dans **transactions de dirigeants** (Form 4).
- Ventes inhabituel par c-suite
- Absence d'achats par c-suite
- Timing suspect

**Seuil de vigilance**: insider_signal > 0.15 = "Élevé"

---

## 🛠️ Étape 2.2: Ajouter Fonction dans composite_engine.py

### Où Ajouter?

**Fichier**: `signals/composite_engine.py`

**Localisation**: Après la fonction `_build_convergence_signal()` (ligne ~302)

### Code à Ajouter

**Nouvelle fonction:**

```python
def _build_triplet_convergence_signal(
    *,
    filing: Filing,
    model_version: str,
    signal_values: dict[str, float | None],
) -> ComputedCompositeSignal:
    """
    Monitor specific convergence of RLDS + forward_pessimism + insider_signal.
    
    Triplet Representation:
    - RLDS: Text-based anomaly (semantic drift)
    - forward_pessimism (GCE): Forward guidance concerns
    - insider_signal (ITA): Insider transaction anomalies
    
    When all 3 converge (elevated), signals high-confidence risk.
    
    Returns:
        ComputedCompositeSignal with triplet_boost and confidence level
    """
    
    # Get signal definition from catalog
    definition = get_signal_definition("triplet_convergence_signal")
    if definition is None:
        definition = SignalDefinition(
            name="triplet_convergence_signal",
            description="Convergence of RLDS, forward_pessimism, and insider_signal"
        )
    
    # Extract individual signals
    rlds = signal_values.get("rlds")
    forward_pessimism = signal_values.get("forward_pessimism")
    insider_signal = signal_values.get("insider_signal")
    
    # Define thresholds (can be different from general CONVERGENCE_THRESHOLDS)
    rlds_threshold = 0.25          # Same as TEXT layer threshold
    forward_pessimism_threshold = 0.25  # Same as TEXT layer threshold
    insider_threshold = 0.15       # Same as BEHAVIOR layer threshold
    
    # Check which signals are elevated
    rlds_elevated = rlds is not None and rlds >= rlds_threshold
    forward_pessimism_elevated = forward_pessimism is not None and forward_pessimism >= forward_pessimism_threshold
    insider_elevated = insider_signal is not None and insider_signal >= insider_threshold
    
    # Count elevated signals
    triplet_signals_elevated = sum([
        rlds_elevated,
        forward_pessimism_elevated,
        insider_elevated
    ])
    
    # Calculate boost based on convergence strength
    triplet_boost = 0.0
    triplet_confidence = "none"
    
    if triplet_signals_elevated == 3:
        # All 3 signals elevated: MAXIMUM CONVERGENCE
        triplet_boost = 0.25
        triplet_confidence = "full"
    elif triplet_signals_elevated == 2:
        # 2 of 3 elevated: STRONG CONVERGENCE
        triplet_boost = 0.15
        triplet_confidence = "strong"
    elif triplet_signals_elevated == 1:
        # Only 1 elevated: WEAK (no boost)
        triplet_boost = 0.0
        triplet_confidence = "weak"
    # 0 elevated: no boost
    
    # Create ComputedCompositeSignal object
    return ComputedCompositeSignal(
        filing_id=filing.id,
        company_id=filing.company_id,
        signal_name="triplet_convergence_signal",
        signal_value=triplet_boost,
        model_version=model_version,
        detail={
            "description": definition.description if definition else "Triplet convergence signal",
            "signal_values": {
                "rlds": rlds,
                "forward_pessimism": forward_pessimism,
                "insider_signal": insider_signal,
            },
            "thresholds": {
                "rlds": rlds_threshold,
                "forward_pessimism": forward_pessimism_threshold,
                "insider_signal": insider_threshold,
            },
            "elevated_status": {
                "rlds": rlds_elevated,
                "forward_pessimism": forward_pessimism_elevated,
                "insider_signal": insider_elevated,
            },
            "triplet_signals_elevated": triplet_signals_elevated,
            "triplet_confidence": triplet_confidence,
            "triplet_boost": triplet_boost,
            
            # Metadata
            "signal_category": "composite",
            "signal_role": "derived",
            "interpretation": {
                "full": "Maximum convergence: text anomaly + pessimistic guidance + insider concerns",
                "strong": "Strong convergence: 2 of 3 indicators present",
                "weak": "Weak convergence: only 1 indicator present",
                "none": "No convergence: no elevated indicators",
            }[triplet_confidence],
            "model_version": model_version,
        },
    )
```

---

## 📌 Étape 2.3: Intégrer dans Pipeline

### Modifier `compute_composite_signals()`

**Où**: Dans la fonction `compute_composite_signals(db, filing_id, model_version)`

**Avant (Ligne ~120):**
```python
convergence = _build_convergence_signal(
    filing=filing,
    model_version=model_version,
    signal_values=signal_values,
)
nci_global = _build_nci_signal(
    db=db,
    filing=filing,
    model_version=model_version,
    signal_values=signal_values,
    convergence=convergence,
    input_resolutions=resolved_inputs,
)
```

**Après (à ajouter):**
```python
convergence = _build_convergence_signal(
    filing=filing,
    model_version=model_version,
    signal_values=signal_values,
)

# ← NEW: Compute triplet convergence
triplet_convergence = _build_triplet_convergence_signal(
    filing=filing,
    model_version=model_version,
    signal_values=signal_values,
)

nci_global = _build_nci_signal(
    db=db,
    filing=filing,
    model_version=model_version,
    signal_values=signal_values,
    convergence=convergence,
    input_resolutions=resolved_inputs,
)
```

### Modifier le Return Statement

**Avant (Ligne ~137):**
```python
return [
    divergence.to_dict(),
    convergence.to_dict(),
    nci_global.to_dict(),
    composite_alias.to_dict(),
]
```

**Après (ajouter triplet_convergence):**
```python
return [
    divergence.to_dict(),
    convergence.to_dict(),
    triplet_convergence.to_dict(),  # ← NEW
    nci_global.to_dict(),
    composite_alias.to_dict(),
]
```

---

## 📊 Étape 2.4: Ajouter au Catalog

### Modifier `signals/catalog.py`

**Ajouter définition dans le dictionnaire `SIGNAL_DEFINITIONS`:**

```python
"triplet_convergence_signal": SignalDefinition(
    name="triplet_convergence_signal",
    description="Convergence of RLDS (text), forward_pessimism (guidance), and insider_signal (insiders)",
    signal_type="composite",
    direction="higher_is_worse",  # Higher boost = more risk
    unit="points",
    computation_layer="composite_engine",
    parent_signals=["rlds", "forward_pessimism", "insider_signal"],
    lookback_periods=1,
),
```

---

## 📈 Étape 2.5: Résultats Attendus

### Exemples de Sorties

**Cas 1: All 3 Converge (Maximum Pain)**
```python
triplet_convergence_signal = {
    "signal_name": "triplet_convergence_signal",
    "signal_value": 0.25,  # Maximum boost
    "detail": {
        "signal_values": {
            "rlds": 0.85,
            "forward_pessimism": 0.72,
            "insider_signal": 0.60,
        },
        "elevated_status": {
            "rlds": True,           # ✅ > 0.25
            "forward_pessimism": True,  # ✅ > 0.25
            "insider_signal": True,     # ✅ > 0.15
        },
        "triplet_signals_elevated": 3,
        "triplet_confidence": "full",
        "interpretation": "Maximum convergence: ...",
    },
}
```

**Cas 2: 2 Converge (Strong Signal)**
```python
triplet_convergence_signal = {
    "signal_value": 0.15,  # Moderate boost
    "detail": {
        "signal_values": {
            "rlds": 0.70,
            "forward_pessimism": 0.10,  # ❌ Low
            "insider_signal": 0.45,
        },
        "elevated_status": {
            "rlds": True,
            "forward_pessimism": False,  # ← Not elevated
            "insider_signal": True,
        },
        "triplet_signals_elevated": 2,
        "triplet_confidence": "strong",
    },
}
```

**Cas 3: None or 1 Signal (No Convergence)**
```python
triplet_convergence_signal = {
    "signal_value": 0.0,  # No boost
    "detail": {
        "triplet_signals_elevated": 1,
        "triplet_confidence": "none",
    },
}
```

---

## ✅ Checkliste Convergence Signal

```
CONCEPTION:
  ☐ Comprendre RLDS, forward_pessimism, insider_signal
  ☐ Définir thresholds (RLDS>0.25, GCE>0.25, ITA>0.15)
  ☐ Logique de boost (3/3=0.25, 2/3=0.15, <2/3=0.0)

IMPLÉMENTATION:
  ☐ Créer _build_triplet_convergence_signal() function
  ☐ Extraire les 3 signaux de signal_values dict
  ☐ Vérifier si élevés vs thresholds
  ☐ Calculer boost + confidence level
  ☐ Retourner ComputedCompositeSignal

INTÉGRATION:
  ☐ Appeler _build_triplet_convergence_signal() dans compute_composite_signals()
  ☐ Ajouter résultat au return list (avant nci_global)
  ☐ Ajouter à signal/catalog.py

TESTS:
  ☐ Test: All 3 signals elevated → boost=0.25
  ☐ Test: 2 signals elevated → boost=0.15
  ☐ Test: 1 signal elevated → boost=0.0
  ☐ Test: Verify signal stored in DB correctly
  ☐ Vérifier que NCI global est mis à jour (prend en compte boost)
```

---

# Responsabilité 3 → Sentinel Quality Monitoring

## 🎯 Objectif

Mettre en place un système de **contrôle qualité** qui :

1. **Vérifie la fraîcheur** des données (90j pour 10-Q, 365j pour 10-K)
2. **Détecte les ventes suspectes** d'insiders (Form 4)
3. **Suit les changements de scoring** (delta NCI)
4. **Génère des alertes** pour l'équipe

---

## 📚 Contexte Existant

### Tables Disponibles

**`nci_scores` table:**
```sql
SELECT 
    id,
    filing_id,
    company_id,
    nci_global,           -- Composite risk score
    convergence_tier,
    layers_elevated,
    confidence,
    coverage_ratio,
    
    -- ⬜ A remplir par Sentinel:
    data_fresh,           -- Is this data stale?
    staleness_reason,     -- Why is it stale?
    
    -- Already populated by composite_engine:
    top_anomalous_paragraphs  -- JSON of anomalous text
    
FROM nci_scores;
```

**`insider_transactions` table:**
```sql
SELECT 
    id,
    company_id,
    insider_name,
    insider_cik,
    insider_title,     -- "CEO", "CFO", "President", etc
    transaction_date,
    transaction_type,
    is_disposition,    -- Is it a sale/disposal?
    shares_transacted,
    shares_held,
    transaction_price
FROM insider_transactions;
```

**`pipeline_events` table:**
```sql
SELECT 
    id,
    event_type,        -- "quality_assessed", "alert_generated", etc
    company_id,
    filing_id,
    details,           -- JSON with context
    created_at
FROM pipeline_events;
```

---

## 🔄 Étape 3.1: Fichier Principal

### Créer `signals/sentinel.py`

**Structure de base:**

```python
# 1. IMPORTS
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from dataclasses import dataclass

# 2. CONSTANTS
DATA_FRESHNESS_THRESHOLD_10Q = 90      # days
DATA_FRESHNESS_THRESHOLD_10K = 365     # days
NCI_DELTA_ALERT_THRESHOLD = 0.15       # Alert if delta > 15 points
NCI_DELTA_CRITICAL_THRESHOLD = 0.25    # Critical if delta > 25 points
UNPLANNED_SALE_DETECTION_THRESHOLD_PCT = 20  # % change in holdings

# 3. DATA CLASSES
@dataclass
class FreshnessStatus:
    is_fresh: bool
    staleness_reason: str | None
    filing_age_days: int
    threshold_days: int

@dataclass
class NCIDeltaAnalysis:
    current_nci: float
    previous_nci: float | None
    nci_delta: float | None
    delta_pct: float | None

@dataclass
class SentinelAlert:
    company_id: int
    filing_id: int
    alert_type: str  # "freshness", "unplanned_sale", "nci_delta", etc
    severity: str     # "low", "medium", "high", "critical"
    title: str
    description: str
    metadata: dict

# 4. MAIN FUNCTIONS (see detailed steps below)
def evaluate_filing_quality(...):
    pass

def validate_nci_data_freshness(...):
    pass

def detect_unplanned_insider_sales(...):
    pass

def compute_nci_delta(...):
    pass

def generate_quality_report(...):
    pass
```

---

## ✅ Étape 3.2: Freshness Validation

### Fonction 1: `validate_nci_data_freshness(filing_id)`

**Logique:**

```python
def validate_nci_data_freshness(filing_id: int) -> FreshnessStatus:
    """
    Check if filing is fresh enough for analysis.
    
    Rules:
    - 10-Q: Must be < 90 days old
    - 10-K: Must be < 365 days old
    - Warning if approaching stale threshold
    """
    
    filing = db.get(Filing, filing_id)
    
    # Step 1: Get form type
    form_type = filing.form_type.upper()  # "10-Q", "10-K"
    
    # Step 2: Set threshold
    if "10-Q" in form_type:
        threshold_days = 90
    elif "10-K" in form_type:
        threshold_days = 365
    else:
        threshold_days = 90  # Default
    
    # Step 3: Calculate age
    now = datetime.now(timezone.utc)
    filed_at = filing.filed_at.replace(tzinfo=timezone.utc)
    filing_age_days = (now - filed_at).days
    
    # Step 4: Check freshness
    is_fresh = filing_age_days <= threshold_days
    staleness_reason = None
    
    if not is_fresh:
        staleness_reason = f"Filing exceeds {form_type} threshold"
    
    warning = filing_age_days >= (threshold_days - 15)  # Warn if 15 days before stale
    
    return FreshnessStatus(
        is_fresh=is_fresh,
        staleness_reason=staleness_reason,
        filing_age_days=filing_age_days,
        threshold_days=threshold_days,
        warning=warning
    )
```

### Cas d'Usage

**10-Q Filing (90-day threshold):**
- Morning of filing (day 0): ✅ Fresh
- 45 days after: ✅ Fresh
- 75 days after: ⚠️ Warning (approaching 90)
- 90 days after: ❌ Stale
- 100 days after: ❌ Very Stale

---

## 👥 Étape 3.3: Unplanned Sales Detection

### Fonction 2: `detect_unplanned_insider_sales(filing_id)`

**Approche:**

```python
def detect_unplanned_insider_sales(filing_id: int) -> list[UnplannedSaleAlert]:
    """
    Detect suspicious insider transactions around filing date.
    
    Look for:
    1. Senior insider (CEO, CFO, President, etc)
    2. Significant dispositions (>20% of holdings)
    3. Timing within ±30 days of filing
    """
    
    filing = db.query(Filing).get(filing_id)
    
    # Step 1: Define time window
    window_start = filing.filed_at - timedelta(days=30)
    window_end = filing.filed_at + timedelta(days=30)
    
    # Step 2: Load transactions in window
    transactions = db.query(InsiderTransaction).filter(
        InsiderTransaction.company_id == filing.company_id,
        InsiderTransaction.transaction_date.between(window_start, window_end)
    ).all()
    
    # Step 3: Filter to senior roles & dispositions
    senior_dispositions = [
        tx for tx in transactions
        if tx.is_disposition  # Only sales/disposals
        and any(role in (tx.insider_title or "") for role in ["CEO", "CFO", "President", "CTO"])
    ]
    
    # Step 4: Calculate % change in holdings
    unplanned_sales = []
    
    for tx in senior_dispositions:
        # Get total holdings before
        initial_holdings = sum(
            t.shares_held or 0
            for t in transactions
            if t.insider_cik == tx.insider_cik and not t.is_disposition
        )
        
        # % change
        if initial_holdings > 0:
            pct_change = (tx.shares_transacted / initial_holdings) * 100
        else:
            pct_change = 0
        
        # Alert if > threshold
        if pct_change >= UNPLANNED_SALE_DETECTION_THRESHOLD_PCT:
            unplanned_sales.append(UnplannedSaleAlert(
                insider_name=tx.insider_name,
                insider_role=tx.insider_title,
                transaction_date=tx.transaction_date,
                percent_change=pct_change,
                shares_transacted=tx.shares_transacted,
                confidence=min(pct_change / 100, 1.0)
            ))
    
    return unplanned_sales
```

### Cas d'Usage

**Example CEO Selling:**
- CEO total shares: 1,000,000
- Transaction within ±30 days: 250,000 shares sold
- % change: 25%
- **Result**: ⚠️ Alert (25% > 20% threshold)

---

## 📊 Étape 3.4: NCI Delta Analysis

### Fonction 3: `compute_nci_delta(filing_id)`

**Logique:**

```python
def compute_nci_delta(filing_id: int) -> NCIDeltaAnalysis:
    """
    Calculate NCI change vs previous similar filing.
    
    Example:
    - Current 10-Q (Q1 2024): NCI = 0.65
    - Previous 10-Q (Q4 2023): NCI = 0.50
    - Delta: +0.15 (30% increase)
    """
    
    filing = db.query(Filing).get(filing_id)
    
    # Step 1: Get current NCI
    current_nci_row = db.query(NciScore).filter(
        NciScore.filing_id == filing_id
    ).order_by(NciScore.created_at.desc()).first()
    
    if current_nci_row is None:
        return NCIDeltaAnalysis(current_nci=0, previous_nci=None, nci_delta=None)
    
    current_nci = current_nci_row.nci_global
    
    # Step 2: Get previous same-form-type filing
    previous_nci_row = db.query(NciScore).join(Filing).filter(
        Filing.company_id == filing.company_id,
        Filing.form_type == filing.form_type,
        Filing.fiscal_year < filing.fiscal_year,
        NciScore.nci_global.isnot(None)
    ).order_by(
        Filing.fiscal_year.desc(),
        Filing.fiscal_quarter.desc()
    ).first()
    
    if previous_nci_row is None:
        return NCIDeltaAnalysis(
            current_nci=current_nci,
            previous_nci=None,
            nci_delta=None
        )
    
    previous_nci = previous_nci_row.nci_global
    
    # Step 3: Calculate delta
    nci_delta = current_nci - previous_nci
    delta_pct = nci_delta / previous_nci if previous_nci > 0 else None
    
    return NCIDeltaAnalysis(
        current_nci=current_nci,
        previous_nci=previous_nci,
        nci_delta=nci_delta,
        delta_pct=delta_pct
    )
```

### Thresholds & Alertes

```
NCI Delta        Alert Level    Action
≤ 0.05           ℹ️  Info       Monitor
0.05–0.15        🟡 Medium     Review
0.15–0.25        🔴 High       Investigate
> 0.25           🚨 Critical   Urgent Action
```

---

## 🔧 Étape 3.5: Main Quality Evaluation Function

### Fonction 4: `evaluate_filing_quality(filing_id)`

```python
def evaluate_filing_quality(filing_id: int) -> dict:
    """
    Complete quality assessment for a filing.
    
    Returns dict with:
    - freshness status
    - unplanned sales
    - nci delta
    - generated alerts
    """
    
    filing = db.query(Filing).get(filing_id)
    
    result = {
        "filing_id": filing_id,
        "company_id": filing.company_id,
        "evaluated_at": datetime.now(timezone.utc),
        "alerts": [],
        "warnings": []
    }
    
    # Check 1: Freshness
    freshness = validate_nci_data_freshness(filing_id)
    result["freshness"] = {
        "is_fresh": freshness.is_fresh,
        "filing_age_days": freshness.filing_age_days,
        "threshold_days": freshness.threshold_days,
    }
    
    if not freshness.is_fresh:
        result["alerts"].append({
            "type": "freshness",
            "severity": "high",
            "message": f"Data is stale ({filing_age_days} days)"
        })
    
    if freshness.warning:
        result["warnings"].append({
            "type": "freshness_warning",
            "message": f"Data approaching stale threshold"
        })
    
    # Check 2: Unplanned Sales
    unplanned_sales = detect_unplanned_insider_sales(filing_id)
    result["unplanned_sales"] = unplanned_sales
    
    if unplanned_sales:
        for sale in unplanned_sales:
            result["alerts"].append({
                "type": "unplanned_sale",
                "severity": "medium",
                "insider": sale.insider_name,
                "message": f"CEO/CFO sold {sale.percent_change}% of holdings"
            })
    
    # Check 3: NCI Delta
    nci_delta = compute_nci_delta(filing_id)
    result["nci_delta"] = {
        "current": nci_delta.current_nci,
        "previous": nci_delta.previous_nci,
        "delta": nci_delta.nci_delta,
        "delta_pct": nci_delta.delta_pct
    }
    
    if nci_delta.nci_delta and nci_delta.nci_delta > NCI_DELTA_CRITICAL_THRESHOLD:
        result["alerts"].append({
            "type": "nci_delta_critical",
            "severity": "critical",
            "message": f"CRITICAL: NCI +{nci_delta.nci_delta:.2f}"
        })
    elif nci_delta.nci_delta and nci_delta.nci_delta > NCI_DELTA_ALERT_THRESHOLD:
        result["alerts"].append({
            "type": "nci_delta_alert",
            "severity": "high",
            "message": f"HIGH: NCI +{nci_delta.nci_delta:.2f}"
        })
    
    return result
```

---

## 📈 Étape 3.6: Résultats Attendus

```python
quality_report = {
    "filing_id": 12345,
    "company_id": 99,
    "evaluated_at": "2024-04-24T10:30:00Z",
    "freshness": {
        "is_fresh": True,
        "filing_age_days": 27,
        "threshold_days": 90
    },
    "unplanned_sales": [
        {
            "insider_name": "John Doe",
            "insider_role": "CEO",
            "percent_change": 22.5,
            "shares_transacted": 225000
        }
    ],
    "nci_delta": {
        "current": 0.68,
        "previous": 0.50,
        "delta": 0.18,
        "delta_pct": 0.36
    },
    "alerts": [
        {
            "type": "unplanned_sale",
            "severity": "medium",
            "insider": "John Doe",
            "message": "CEO sold 22.5% of holdings"
        },
        {
            "type": "nci_delta_alert",
            "severity": "high",
            "message": "HIGH: NCI +0.18"
        }
    ],
    "warnings": []
}
```

---

## ✅ Checkliste Sentinel

```
CONCEPTION:
  ☐ Comprendre DATA_FRESHNESS_THRESHOLD_10Q (90 days)
  ☐ Comprendre DATA_FRESHNESS_THRESHOLD_10K (365 days)
  ☐ Définir NCI_DELTA_ALERT_THRESHOLD (0.15)
  ☐ Définir UNPLANNED_SALE_DETECTION_THRESHOLD_PCT (20%)

IMPLÉMENTATION:
  ☐ Créer FreshnessStatus dataclass
  ☐ Créer NCIDeltaAnalysis dataclass
  ☐ Créer SentinelAlert dataclass
  ☐ Implémenter validate_nci_data_freshness()
  ☐ Implémenter detect_unplanned_insider_sales()
  ☐ Implémenter compute_nci_delta()
  ☐ Implémenter evaluate_filing_quality()

ALERTES:
  ☐ Freshness alerts (if stale)
  ☐ Unplanned sales alerts (if >20% holdings sold)
  ☐ NCI delta alerts (if >0.15 increase)
  ☐ NCI delta critical (if >0.25 increase)

TESTS:
  ☐ Test freshness check (90d threshold for 10-Q)
  ☐ Test unplanned sales detection
  ☐ Test NCI delta calculation
  ☐ Test alert generation
  ☐ Test batch quality report generation

DATABASE:
  ☐ Update nci_scores.data_fresh column
  ☐ Update nci_scores.staleness_reason column
  ☐ Create quality_alerts table (if needed)
```

---

# Responsabilité 4 → LLM Explicability

## 🎯 Objectif

Utiliser un **service LLM (Spring AI - Java backend)** pour générer des **explications narratives** automatiques des scores de risque NCI.

**Flux:**
```
Paragraph anormaux (déjà détectés)
    ↓
Format prompt pour LLM
    ↓
POST à Spring AI service (Java)
    ↓
LLM génère narration
    ↓
Extrait risks + severity + actionability
    ↓
Stocke en DB
    ↓
API retourne au frontend
```

---

## 📚 Contexte Existant

### Données Disponibles

**`nci_scores` table (déjà peuplée):**
```sql
SELECT 
    id,
    filing_id,
    company_id,
    nci_global,
    convergence_tier,
    layers_elevated,
    
    -- Already populated by composite_engine:
    top_anomalous_paragraphs  -- JSON list of 5-10 anomalous texts
    
FROM nci_scores;
```

**Exemple de `top_anomalous_paragraphs`:**
```json
[
  {
    "text": "Management expects significant headwinds in Q2 due to supply chain disruptions...",
    "anomaly_score": 0.92,
    "section": "MD&A"
  },
  {
    "text": "Revenue growth deceleration is attributed to market challenges in certain segments...",
    "anomaly_score": 0.78,
    "section": "MD&A"
  }
]
```

### Spring AI Service (À Déployer)

**Endpoint**: `POST http://localhost:8080/api/explain/filing-risk`

**Request Format:**
```json
{
  "filing_id": 12345,
  "company_name": "TechCorp Inc",
  "fiscal_period": "2024Q1",
  "nci_score": 0.68,
  "top_anomalous_paragraphs": [
    {"text": "...", "anomaly_score": 0.92},
    {"text": "...", "anomaly_score": 0.78}
  ]
}
```

**Response Format:**
```json
{
  "narrative": "This filing reveals significant operational concerns. Management's guidance suggests...",
  "key_risks": ["supply_chain_disruption", "revenue_deceleration", "margin_pressure"],
  "severity_level": "high",
  "actionability": "urgent",
  "confidence": 0.87
}
```

---

## 🛠️ Étape 4.1: Créer Client Python

### Créer `signals/explainability_client.py`

```python
# IMPORTS
import httpx
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# CONFIG
SPRING_AI_SERVICE_URL = "http://localhost:8080"
SPRING_AI_EXPLAIN_ENDPOINT = "/api/explain/filing-risk"
SPRING_AI_TIMEOUT_SECONDS = 30

# DATA CLASSES
@dataclass
class ExplanationRequest:
    """LLM explanation request"""
    filing_id: int
    company_name: str
    fiscal_period: str
    nci_score: float
    top_anomalous_paragraphs: list[dict]
    convergence_tier: str | None = None
    layers_elevated: int | None = None

@dataclass
class ExplanationResponse:
    """LLM explanation response"""
    filing_id: int
    narrative: str
    key_risks: list[str]
    severity_level: str  # "low", "medium", "high", "critical"
    actionability: str   # "routine", "monitor", "urgent", "critical"
    confidence: float    # 0.0-1.0
    generated_at: datetime = None

# MAIN FUNCTIONS (see detailed steps below)
def load_and_explain_nci_score(filing_id: int) -> ExplanationResponse | None:
    pass

def call_spring_ai_explain(request: ExplanationRequest) -> ExplanationResponse | None:
    pass

def batch_explain_nci_scores(company_id: int | None = None, lookback_days: int = 30) -> dict:
    pass

def prepare_llm_prompt(paragraphs: list[dict], metadata: dict) -> str:
    pass
```

---

## 📝 Étape 4.2: Préparer le Prompt

### Fonction: `prepare_llm_prompt()`

```python
def prepare_llm_prompt(
    top_anomalous_paragraphs: list[dict],
    filing_metadata: dict
) -> str:
    """
    Format paragraphs anormaux + context pour LLM.
    
    Inputs:
    - top_anomalous_paragraphs: List of {"text": "...", "anomaly_score": 0.9}
    - filing_metadata: {"company_name": "...", "fiscal_period": "...", "nci_score": 0.68}
    
    Returns:
    - Structured prompt for LLM
    """
    
    prompt = f"""
You are a financial analyst AI. Analyze the following anomalous paragraphs from a company filing and provide insights.

FILING CONTEXT:
- Company: {filing_metadata.get('company_name', 'Unknown')}
- Fiscal Period: {filing_metadata.get('fiscal_period', 'Unknown')}
- Risk Score (NCI): {filing_metadata.get('nci_score', 0.0):.2f} (0-1 scale, higher = more risky)

ANOMALOUS PARAGRAPHS DETECTED:
These paragraphs deviate significantly from the company's historical filings.
"""
    
    for i, para in enumerate(top_anomalous_paragraphs[:5], 1):  # Top 5
        text = para.get("text", "")
        anomaly_score = para.get("anomaly_score", 0.0)
        section = para.get("section", "Unknown")
        
        prompt += f"""
[Paragraph {i}] 
Section: {section}
Anomaly Score: {anomaly_score:.2f} (0-1, higher = more anomalous)
Text:
"{text}"

"""
    
    prompt += """
ANALYSIS REQUIRED:
1. Why are these paragraphs anomalous compared to historical context?
2. What key risks or concerns do you identify in this text?
3. Based on the anomalies, what is the severity level?
   - "low": Minor observations, likely routine business variations
   - "medium": Notable changes but not necessarily alarming
   - "high": Significant concerns that warrant attention
   - "critical": Major red flags requiring urgent review
4. What is the recommended actionability?
   - "routine": Standard monitoring, no action needed
   - "monitor": Keep watch for developments
   - "urgent": Should be reviewed soon
   - "critical": Requires immediate investigation
5. List 2-4 specific key risks identified.
6. Your confidence in this assessment (0.0-1.0)?

RESPONSE FORMAT (JSON):
{
  "narrative": "A concise 2-3 sentence summary of your findings...",
  "key_risks": ["risk1", "risk2", "risk3"],
  "severity_level": "high",
  "actionability": "urgent",
  "confidence": 0.85
}

Do NOT include any other text, ONLY return valid JSON.
"""
    
    return prompt
```

---

## 🔗 Étape 4.3: Appeler Spring AI Service

### Fonction: `call_spring_ai_explain()`

```python
def call_spring_ai_explain(request: ExplanationRequest) -> ExplanationResponse | None:
    """
    Call Spring AI service to generate explanation.
    
    Args:
        request: ExplanationRequest
    
    Returns:
        ExplanationResponse with LLM output, or None if failed
    """
    
    logger.info(f"Calling Spring AI for filing_id={request.filing_id}")
    
    # Build URL
    url = f"{SPRING_AI_SERVICE_URL}{SPRING_AI_EXPLAIN_ENDPOINT}"
    
    # Prepare payload
    payload = {
        "filing_id": request.filing_id,
        "company_name": request.company_name,
        "fiscal_period": request.fiscal_period,
        "nci_score": request.nci_score,
        "top_anomalous_paragraphs": request.top_anomalous_paragraphs,
        "convergence_tier": request.convergence_tier,
        "layers_elevated": request.layers_elevated,
    }
    
    try:
        # HTTP POST request
        with httpx.Client(timeout=SPRING_AI_TIMEOUT_SECONDS) as client:
            http_response = client.post(url, json=payload)
            http_response.raise_for_status()  # Raise on 4xx/5xx
        
        # Parse response
        response_data = http_response.json()
        
        logger.info(f"✅ Received explanation from Spring AI for filing {request.filing_id}")
        
        return ExplanationResponse(
            filing_id=request.filing_id,
            narrative=str(response_data.get("narrative", "")),
            key_risks=response_data.get("key_risks", []),
            severity_level=str(response_data.get("severity_level", "medium")),
            actionability=str(response_data.get("actionability", "monitor")),
            confidence=float(response_data.get("confidence", 0.5)),
            generated_at=datetime.now(timezone.utc)
        )
    
    except httpx.HTTPError as e:
        logger.error(f"❌ HTTP error: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return None
```

---

## 🔄 Étape 4.4: Pipeline End-to-End

### Fonction: `load_and_explain_nci_score()`

```python
def load_and_explain_nci_score(
    filing_id: int,
    nci_score_id: int | None = None
) -> ExplanationResponse | None:
    """
    Complete pipeline: load NCI score + generate explanation.
    
    Workflow:
    1. Load filing + NCI score from DB
    2. Extract top_anomalous_paragraphs
    3. Format request for Spring AI
    4. Call Spring AI service
    5. Store response in DB
    6. Return response
    """
    
    logger.info(f"Loading NCI score for explanation: filing_id={filing_id}")
    
    # Step 1: Load filing
    filing = db.query(Filing).get(filing_id)
    if filing is None:
        logger.error(f"Filing not found: {filing_id}")
        return None
    
    # Step 2: Load NCI score
    nci_query = db.query(NciScore).filter(NciScore.filing_id == filing_id)
    if nci_score_id:
        nci_query = nci_query.filter(NciScore.id == nci_score_id)
    else:
        nci_query = nci_query.order_by(NciScore.created_at.desc())
    
    nci_score = nci_query.limit(1).first()
    if nci_score is None:
        logger.error(f"NCI score not found for filing: {filing_id}")
        return None
    
    # Step 3: Extract paragraphs
    top_anomalous_paragraphs = []
    if isinstance(nci_score.top_anomalous_paragraphs, list):
        top_anomalous_paragraphs = nci_score.top_anomalous_paragraphs
    elif isinstance(nci_score.top_anomalous_paragraphs, dict):
        paras = nci_score.top_anomalous_paragraphs.get("paragraphs")
        if isinstance(paras, list):
            top_anomalous_paragraphs = paras
    
    if not top_anomalous_paragraphs:
        logger.warning(f"No anomalous paragraphs for filing: {filing_id}")
        return None  # Nothing to explain
    
    # Step 4: Build request
    company_name = filing.company.name if filing.company else f"Company {filing.company_id}"
    fiscal_period = f"{filing.fiscal_year}Q{filing.fiscal_quarter}" if filing.fiscal_quarter else str(filing.fiscal_year)
    
    request = ExplanationRequest(
        filing_id=filing.id,
        company_name=company_name,
        fiscal_period=fiscal_period,
        nci_score=float(nci_score.nci_global) if nci_score.nci_global else 0.0,
        top_anomalous_paragraphs=top_anomalous_paragraphs,
        convergence_tier=nci_score.convergence_tier,
        layers_elevated=nci_score.layers_elevated,
    )
    
    # Step 5: Call Spring AI
    response = call_spring_ai_explain(request)
    if response is None:
        logger.error(f"Failed to generate explanation for filing: {filing_id}")
        return None
    
    # Step 6: Store response
    logger.info(f"Storing explanation: filing={filing_id}, severity={response.severity_level}")
    
    # TODO: Save response to DB (nci_scores or llm_explanations table)
    # db.execute(UPDATE(NciScore).where(...).values(llm_narrative=response.narrative, ...))
    
    return response
```

---

## 📦 Étape 4.5: Batch Processing

### Fonction: `batch_explain_nci_scores()`

```python
def batch_explain_nci_scores(
    company_id: int | None = None,
    lookback_days: int = 30
) -> dict:
    """
    Batch process explanations for recent NCI scores.
    
    Useful for:
    - Daily batch runs (off-peak)
    - Backfilling explanations
    - Re-running failed explanations
    """
    
    result = {
        "explanations_generated": 0,
        "explanations_failed": 0,
        "errors": []
    }
    
    # Load recent NCI scores
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    
    query = db.query(NciScore).filter(
        NciScore.created_at >= cutoff,
        NciScore.nci_global >= 0.50,  # Only high-risk scores
        NciScore.top_anomalous_paragraphs.isnot(None)
    ).order_by(NciScore.created_at.desc())
    
    if company_id:
        query = query.filter(NciScore.company_id == company_id)
    
    nci_scores = query.all()
    logger.info(f"Found {len(nci_scores)} NCI scores to explain")
    
    # Process each score
    for nci_score in nci_scores:
        try:
            response = load_and_explain_nci_score(nci_score.filing_id)
            if response:
                result["explanations_generated"] += 1
            else:
                result["explanations_failed"] += 1
                result["errors"].append(f"No response for filing_{nci_score.filing_id}")
        except Exception as e:
            result["explanations_failed"] += 1
            result["errors"].append(f"Exception for filing_{nci_score.filing_id}: {str(e)}")
    
    logger.info(f"Batch complete: {result['explanations_generated']} generated, {result['explanations_failed']} failed")
    return result
```

---

## ✅ Checkliste Explicability

```
CONCEPTION:
  ☐ Comprendre Spring AI endpoint
  ☐ Définir format de request/response
  ☐ Identifier top_anomalous_paragraphs déjà disponibles

IMPLÉMENTATION:
  ☐ Créer ExplanationRequest dataclass
  ☐ Créer ExplanationResponse dataclass
  ☐ Implémenter prepare_llm_prompt()
  ☐ Implémenter call_spring_ai_explain()
  ☐ Implémenter load_and_explain_nci_score()
  ☐ Implémenter batch_explain_nci_scores()

INTÉGRATION SPRING AI:
  ☐ Déployer service Spring AI (Java)
  ☐ Configurer endpoint POST /api/explain/filing-risk
  ☐ Tester HTTP connectivity
  ☐ Configurer SPRING_AI_SERVICE_URL

TESTS:
  ☐ Test prompt generation
  ☐ Test HTTP call to Spring AI (mock)
  ☐ Test response parsing
  ☐ Test batch processing
  ☐ Test error handling (service down, etc)

DATABASE:
  ☐ Store llm_narrative in nci_scores or new table
  ☐ Store severity_level + actionability
  ☐ Store generation timestamp + confidence
```

---

# Intégration Globale

## 🔄 Ordre d'Implémentation

```
WEEK 1: Foundation
  1️⃣ Sector Autoencoder
     - Train models per industry
     - Score embeddings
     - Verify anomaly detection

WEEK 2: Signals
  2️⃣ Triplet Convergence
     - Add _build_triplet_convergence_signal()
     - Integrate into composite pipeline
     - Test signal values

WEEK 3: Quality
  3️⃣ Sentinel
     - Deploy freshness checks
     - Implement insider sales detection
     - Generate alerts

WEEK 4: Explanation
  4️⃣ LLM Explicability
     - Deploy Spring AI backend
     - Integrate Python client
     - Batch process explanations
```

---

## 🔗 Data Dependencies

```
embeddings (1024-dim vectors)
    ↓ [Autoencoder scores]
reconstruction_error, anomaly_score
    ↓
signal_scores (text, numeric, behavior, market, sentiment)
    ↓ [Composite engine + Triplet convergence]
triplet_convergence_signal, nci_global
    ↓
nci_scores (with top_anomalous_paragraphs)
    ├─ [Sentinel validation]
    │   └─ quality_alerts + data_fresh flags
    └─ [LLM Explicability]
        └─ llm_narrative + severity + actionability
```

---

## 📊 API Response Example

```json
GET /api/nci/12345

{
  "filing_id": 12345,
  "company_id": 99,
  "company_name": "TechCorp Inc",
  "fiscal_period": "2024Q1",
  "nci_global": 0.68,
  "nci_interpretation": "HIGH RISK",
  
  "composite_signals": {
    "convergence_signal": 0.08,
    "triplet_convergence_signal": 0.25,  ← NEW
    "divergence_signal": -0.12,
    "layers_elevated": 4
  },
  
  "quality_metrics": {
    "data_fresh": true,
    "freshness_age_days": 27,
    "confidence": "high",
    "coverage_ratio": 0.95
  },
  
  "alerts": [
    {
      "type": "unplanned_sale",
      "severity": "medium",
      "insider": "John Doe (CEO)",
      "message": "CEO sold 22% of holdings within ±30 days of filing"
    },
    {
      "type": "nci_delta_alert",
      "severity": "high",
      "message": "NCI increased +0.18 (36%) vs Q4 2023"
    }
  ],
  
  "llm_explanation": {
    "narrative": "This 10-Q filing reveals significant operational headwinds. Management guidance has shifted to pessimism, citing supply chain challenges and revenue pressure across key segments. Notably, the CEO executed significant share disposals during the filing period, suggesting possible concern about near-term prospects.",
    "key_risks": [
      "supply_chain_disruption",
      "revenue_deceleration",
      "insider_selling",
      "margin_compression"
    ],
    "severity_level": "high",
    "actionability": "urgent",
    "confidence": 0.87,
    "generated_at": "2024-04-24T10:35:00Z"
  }
}
```

---

## 🚀 Installation & Déploiement

### Prérequis

```bash
# Python dependencies (already in requirements.txt)
- torch==2.9.0              # Autoencoder
- sqlalchemy==2.0.30        # ORM
- httpx==0.27.0             # HTTP client
- numpy==1.26.4             # Arrays

# External services
- PostgreSQL (embeddings, signals, nci_scores tables)
- Spring AI service (Java backend at http://localhost:8080)
```

### Commandes Clés

```bash
# 1. Train autoencoders (one-time or quarterly)
python -c "from signals.sector_autoencoder import train_sector_autoencoders; train_sector_autoencoders()"

# 2. Score new filings
python -c "from signals.sector_autoencoder import compute_embeddings_anomaly_scores; compute_embeddings_anomaly_scores(filing_id=X)"

# 3. Evaluate quality
python -c "from signals.sentinel import evaluate_filing_quality; evaluate_filing_quality(filing_id=X)"

# 4. Generate explanations
python -c "from signals.explainability_client import batch_explain_nci_scores; batch_explain_nci_scores()"
```

---

## 🎯 Profil de Succès

✅ **Autoencoder Works If:**
- Anomaly scores are between 0-1
- ~95% of training data has scores < 0.75
- High-anomaly paragraphs correlate with RLDS signal

✅ **Triplet Convergence Works If:**
- Signal returns 0.25 when all 3 inputs elevated
- Signal returns 0.15 when 2/3 inputs elevated
- Signal stored in DB correctly

✅ **Sentinel Works If:**
- Fresh data flagged correctly (90d for 10-Q, 365d for 10-K)
- Insider sales detected when >20% holdings sold
- Delta NCI alerts triggered at >0.15 threshold

✅ **Explicability Works If:**
- Spring AI service responds with JSON
- LLM narrative matches filing context
- Severity/actionability align with NCI score

---

## 🐛 Dépannage

### Autoencoder

**Problem**: MSE scores too high across all data
- **Solution**: Increase bottleneck size (256 → 512)
- **Solution**: Lower threshold percentile (95 → 90)

**Problem**: Models not saving
- **Solution**: Verify `data/autoencoder_models/` directory exists
- **Solution**: Check file write permissions

### Convergence

**Problem**: Triplet boost always 0
- **Solution**: Verify rlds, forward_pessimism, insider_signal exist in signal_values
- **Solution**: Lower thresholds (0.25 → 0.20)

### Sentinel

**Problem**: No alerts generated
- **Solution**: Verify insider_transactions table is populated
- **Solution**: Check NCI delta calculation (previous filing must exist)

### Explicability

**Problem**: Spring AI service unreachable
- **Solution**: Verify service is running at SPRING_AI_SERVICE_URL
- **Solution**: Check HTTP connectivity: `curl http://localhost:8080/health`

---

## 📞 Support & Next Steps

1. **Questions**: Refer to this document
2. **Coding Help**: Check examples in each responsibility section
3. **Database**: Verify tables exist with correct schema
4. **Testing**: Run unit tests after each implementation
5. **Deployment**: Follow weekly roadmap above

---

**Version**: 1.0  
**Last Updated**: 2026-04-24  
**Status**: Ready for Implementation
