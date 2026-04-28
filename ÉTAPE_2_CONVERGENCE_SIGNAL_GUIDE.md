# 🔗 ÉTAPE 2: Signal de Convergence Triplet — Guide Détaillé

**Statut**: Prêt pour implémentation (après ÉTAPE 1 ✅)  
**Date**: 27 Avril 2026  
**Fichier à modifier**: `signals/composite_engine.py`  
**Fichier secondaire**: `signals/catalog.py`  

---

## 📋 Table des Matières

1. [C'est quoi cette étape ?](#cest-quoi-cette-étape)
2. [Les 3 signaux en entrée](#les-3-signaux-en-entrée)
3. [La logique de convergence](#la-logique-de-convergence)
4. [Implémentation pas à pas](#implémentation-pas-à-pas)
5. [Intégration dans le pipeline](#intégration-dans-le-pipeline)
6. [Tests et validation](#tests-et-validation)
7. [Exemples concrets](#exemples-concrets)
8. [Troubleshooting](#troubleshooting)

---

## C'est quoi cette étape ?

### 🎯 Objectif en une phrase

> Créer un **signal d'alerte renforcé** qui se déclenche quand **3 indicateurs de risque** sont élevés **en même temps**.

### 🧠 L'idée simple

Imagine 3 détecteurs de fumée dans une maison :

| Détecteur | Ce qu'il surveille | Nom technique |
|---|---|---|
| 🔥 Détecteur 1 | Le **texte** du rapport financier a changé anormalement | `rlds` |
| 😟 Détecteur 2 | La direction est **pessimiste** sur le futur | `forward_pessimism` (GCE) |
| 💰 Détecteur 3 | Les **dirigeants vendent** leurs actions | `insider_signal` (ITA) |

- **1 seul** détecteur sonne → Peut-être rien de grave
- **2 détecteurs** sonnent → Attention, quelque chose se passe
- **3 détecteurs** sonnent → ⚠️ **ALERTE MAXIMALE**, il y a probablement un vrai problème

C'est exactement ce que fait le **Triplet Convergence Signal** : il donne un **boost de risque** quand plusieurs indicateurs convergent.

### 📍 Où ça se place dans le pipeline ?

```
ÉTAPE 1 ✅ (Déjà fait)
  Autoencoder → anomaly_score dans embeddings table
      ↓
ÉTAPE 2 ⭐ (À FAIRE MAINTENANT)
  Triplet Convergence → triplet_convergence_signal dans signal_scores table
      ↓
ÉTAPE 3 (Après)
  Sentinel → quality_alerts
      ↓
ÉTAPE 4 (Après)
  LLM Explicability → narrative textuelle
```

---

## Les 3 signaux en entrée

### Signal 1: RLDS (Risk Lexical Drift Score)

**Fichier source**: `signals/text_signals.py`  
**Table**: `signal_scores` (signal_name = `'rlds'`)

**Ce qu'il fait**: Compare le texte du rapport actuel avec le précédent.
```
Exemple:
  - Rapport Q1 2025: g "Revenue grew 20% thanks to strong demand..."
  - Rapport Q2 2025: "Revenue declined significantly due to unprecedented challenges..."
  
  → RLDS = 0.85 (très élevé = le texte a BEAUCOUP changé)
```

**Seuil de vigilance**: `rlds >= 0.25` = élevé  
**Poids dans NCI**: 0.20 (le plus important — voir `policies.py` ligne 84)

---

### Signal 2: forward_pessimism (GCE)

**Fichier source**: `signals/text_signals.py`  
**Table**: `signal_scores` (signal_name = `'forward_pessimism'`)

**Ce qu'il fait**: Analyse le ton de la direction quand elle parle du futur.

```
Exemple:
  - Optimiste: "We expect continued growth and improved margins..."
    → forward_pessimism = 0.10 (bas = tout va bien)
  
  - Pessimiste: "We anticipate significant headwinds and uncertain outlook..."
    → forward_pessimism = 0.72 (élevé = direction inquiète)
```

**Mots clés surveillés** (voir `policies.py` lignes 6-30):
- `expect`, `outlook`, `guidance`, `forecast`, `anticipate`
- `headwind`, `uncertain`, `challenge`

**Seuil de vigilance**: `forward_pessimism >= 0.25` = élevé  
**Poids dans NCI**: 0.07

---

### Signal 3: insider_signal (ITA)

**Fichier source**: `signals/behavior_signals.py`  
**Table**: `signal_scores` (signal_name = `'insider_signal'`)

**Ce qu'il fait**: Détecte si les dirigeants (CEO, CFO...) vendent massivement leurs actions.

```
Exemple:
  - Normal: Le CFO vend 2% de ses actions → insider_signal = 0.08
  - Suspect: Le CEO + CFO vendent 30% de leurs actions → insider_signal = 0.65
```

**Seuil de vigilance**: `insider_signal >= 0.15` = élevé  
**Poids dans NCI**: 0.10

---

### ⚠️ Pourquoi ces 3 spécifiquement ?

Quand les 3 convergent, ça raconte une histoire cohérente :

```
1. Le texte a changé anormalement (RLDS ↑)
   → "L'entreprise communique différemment"

2. La direction est pessimiste (GCE ↑)
   → "Et ce qu'elle dit est négatif"

3. Les dirigeants vendent leurs actions (ITA ↑)
   → "Et ils mettent leur argent en sécurité"

= 🚨 TRIPLE CONVERGENCE = Signal très fort de risque réel
```

---

## La logique de convergence

### 📊 Tableau de boost

| Signaux élevés | Boost ajouté au NCI | Confidence | Interprétation |
|---|---|---|---|
| **3/3** | **+0.25** | `"full"` | ⚠️ Convergence maximale |
| **2/3** | **+0.15** | `"strong"` | 🟡 Convergence forte |
| **1/3** | **+0.00** | `"weak"` | ✅ Pas de convergence |
| **0/3** | **+0.00** | `"none"` | ✅ Aucun signal élevé |

### 📐 Seuils utilisés

Ces seuils viennent de `policies.py` (les mêmes que pour la convergence 5-couches existante) :

```python
# Seuils pour considérer un signal comme "élevé"
RLDS_THRESHOLD          = 0.25   # Même que CONVERGENCE_THRESHOLDS["text"]
FORWARD_PESSIMISM_THRESHOLD = 0.25   # Même seuil
INSIDER_SIGNAL_THRESHOLD    = 0.15   # Même que CONVERGENCE_THRESHOLDS["behavior"]
```

### 🔢 Calcul simple

```python
# Pseudo-code du calcul
rlds_elevated = rlds >= 0.25               # True/False
pessimism_elevated = forward_pessimism >= 0.25  # True/False
insider_elevated = insider_signal >= 0.15       # True/False

count = rlds_elevated + pessimism_elevated + insider_elevated  # 0, 1, 2 ou 3

if count == 3:
    boost = 0.25    # Maximum
elif count == 2:
    boost = 0.15    # Fort
else:
    boost = 0.00    # Rien
```

---

## Implémentation pas à pas

### 📁 Fichier 1: `signals/composite_engine.py` (MODIFIER)

#### Étape A: Ajouter la nouvelle fonction

**Où l'ajouter ?** Après la fonction `_build_convergence_signal()` (après la ligne 344).

```python
def _build_triplet_convergence_signal(
    *,
    filing: Filing,
    model_version: str,
    signal_values: dict[str, float | None],
) -> ComputedCompositeSignal:
    """
    Surveille la convergence spécifique de 3 signaux clés:
    RLDS (texte) + forward_pessimism (guidance) + insider_signal (insiders).
    
    Quand les 3 sont élevés en même temps → boost de risque maximal.
    """
    definition = get_signal_definition("triplet_convergence_signal")

    # ── Extraire les 3 signaux ──
    rlds = signal_values.get("rlds")
    forward_pessimism = signal_values.get("forward_pessimism")
    insider_signal = signal_values.get("insider_signal")

    # ── Seuils ──
    rlds_threshold = 0.25
    forward_pessimism_threshold = 0.25
    insider_threshold = 0.15

    # ── Vérifier lesquels sont élevés ──
    rlds_elevated = rlds is not None and rlds >= rlds_threshold
    pessimism_elevated = forward_pessimism is not None and forward_pessimism >= forward_pessimism_threshold
    insider_elevated = insider_signal is not None and insider_signal >= insider_threshold

    # ── Compter ──
    count = sum([rlds_elevated, pessimism_elevated, insider_elevated])

    # ── Calculer le boost ──
    if count == 3:
        triplet_boost = 0.25
        triplet_confidence = "full"
    elif count == 2:
        triplet_boost = 0.15
        triplet_confidence = "strong"
    elif count == 1:
        triplet_boost = 0.0
        triplet_confidence = "weak"
    else:
        triplet_boost = 0.0
        triplet_confidence = "none"

    # ── Construire le résultat ──
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
                "forward_pessimism": pessimism_elevated,
                "insider_signal": insider_elevated,
            },
            "triplet_signals_elevated": count,
            "triplet_confidence": triplet_confidence,
            "triplet_boost": triplet_boost,
            "interpretation": {
                "full": "Convergence maximale: anomalie texte + pessimisme guidance + ventes insiders",
                "strong": "Convergence forte: 2 des 3 indicateurs présents",
                "weak": "Convergence faible: 1 seul indicateur présent",
                "none": "Aucune convergence: aucun indicateur élevé",
            }[triplet_confidence],
            "signal_category": "composite",
            "signal_role": "derived",
            "model_version": model_version,
        },
    )
```

#### Étape B: Appeler la fonction dans `compute_composite_signals()`

**Où ?** Dans la fonction `compute_composite_signals()` (lignes 95-152).

**Ajouter l'appel** entre `convergence` et `nci_global` (après ligne 130) :

```python
    # Code existant (lignes 126-130)
    convergence = _build_convergence_signal(
        filing=filing,
        model_version=model_version,
        signal_values=signal_values,
    )
    
    # ← NOUVEAU: Ajouter ici
    triplet_convergence = _build_triplet_convergence_signal(
        filing=filing,
        model_version=model_version,
        signal_values=signal_values,
    )

    # Code existant (lignes 131-138)
    nci_global = _build_nci_signal(
        ...
    )
```

#### Étape C: Ajouter au return

**Modifier le return** (lignes 147-152) pour inclure le nouveau signal :

```python
    # AVANT (actuel):
    return [
        divergence.to_dict(),
        convergence.to_dict(),
        nci_global.to_dict(),
        composite_alias.to_dict(),
    ]

    # APRÈS (nouveau):
    return [
        divergence.to_dict(),
        convergence.to_dict(),
        triplet_convergence.to_dict(),    # ← NOUVEAU
        nci_global.to_dict(),
        composite_alias.to_dict(),
    ]
```

---

### 📁 Fichier 2: `signals/catalog.py` (MODIFIER)

Ajouter la définition du nouveau signal dans le dictionnaire `SIGNAL_DEFINITIONS` (avant la fermeture `}` ligne 129) :

```python
    "triplet_convergence_signal": SignalDefinition(
        name="triplet_convergence_signal",
        layer="composite",
        description="Convergence ciblée de RLDS (texte), forward_pessimism (guidance), et insider_signal (insiders). Boost de risque quand 2+ signaux sont élevés.",
    ),
```

---

## Intégration dans le pipeline

### Comment ça s'exécute ?

Le triplet convergence signal est **automatiquement calculé** quand on lance le pipeline de signaux composites. Il n'y a **aucun script séparé** à exécuter.

```
python run_signals.py --filing-id 123
    ↓
signals_pipeline.py
    ↓
compute_and_store_composite_signals(filing_id=123)
    ↓
compute_composite_signals()
    ├── _build_divergence_signal()          # Existant
    ├── _build_convergence_signal()         # Existant (5 couches)
    ├── _build_triplet_convergence_signal() # ← NOUVEAU
    ├── _build_nci_signal()                 # Existant
    └── _build_alias_signal()              # Existant
    ↓
upsert_signal_scores()  → INSERT/UPDATE dans signal_scores table
```

### Où est stocké le résultat ?

```sql
-- Dans la table signal_scores
SELECT * FROM signal_scores 
WHERE signal_name = 'triplet_convergence_signal' 
AND filing_id = 123;

-- Résultat:
-- id | filing_id | company_id | signal_name                    | signal_value | detail
-- 99 | 123       | 42         | triplet_convergence_signal     | 0.25         | {"triplet_confidence":"full",...}
```

### Flux de données complet

```
signal_scores table (déjà peuplée par les pipelines précédents)
  ├── rlds = 0.85                  ← text_signals.py
  ├── forward_pessimism = 0.72     ← text_signals.py  
  └── insider_signal = 0.60       ← behavior_signals.py
      ↓
_build_triplet_convergence_signal()
      ↓
Résultat: triplet_convergence_signal = 0.25 (full convergence)
      ↓
signal_scores table (nouvelle ligne ajoutée)
  └── triplet_convergence_signal = 0.25
```

---

## Tests et validation

### Test 1: Vérifier le code compile

```bash
python -c "from signals.composite_engine import compute_composite_signals; print('✅ Import OK')"
```

### Test 2: Vérifier le catalog

```bash
python -c "
from signals.catalog import get_signal_definition
defn = get_signal_definition('triplet_convergence_signal')
assert defn is not None, 'Signal not in catalog!'
print(f'✅ Signal trouvé: {defn.name} ({defn.layer})')
print(f'   Description: {defn.description}')
"
```

### Test 3: Exécuter sur un filing existant

```bash
python -c "
from app.db.session import SessionLocal
from signals.composite_engine import compute_composite_signals

session = SessionLocal()

# Prendre un filing qui a déjà des signaux
from app.db.models import Filing
filing = session.query(Filing).filter(
    Filing.is_signal_scored == True
).order_by(Filing.filed_at.desc()).first()

if filing:
    print(f'Testing on filing {filing.id} ({filing.company.name})...')
    results = compute_composite_signals(session, filing_id=filing.id)
    
    for signal in results:
        name = signal['signal_name']
        value = signal['signal_value']
        print(f'  {name}: {value}')
        
        # Vérifier le nouveau signal
        if name == 'triplet_convergence_signal':
            detail = signal['detail']
            print(f'    → Signals elevated: {detail[\"triplet_signals_elevated\"]}/3')
            print(f'    → Confidence: {detail[\"triplet_confidence\"]}')
            print(f'    → Boost: {detail[\"triplet_boost\"]}')
            print(f'    → RLDS={detail[\"signal_values\"][\"rlds\"]}, '
                  f'Pessimism={detail[\"signal_values\"][\"forward_pessimism\"]}, '
                  f'Insider={detail[\"signal_values\"][\"insider_signal\"]}')

session.close()
"
```

### Test 4: Vérifier les 3 cas de convergence

```bash
python -c "
# Test unitaire sans BD
from unittest.mock import MagicMock

# Simuler un filing
filing = MagicMock()
filing.id = 1
filing.company_id = 42

# Importer la fonction (après modification)
from signals.composite_engine import _build_triplet_convergence_signal

# CAS 1: Les 3 signaux élevés → boost = 0.25
result = _build_triplet_convergence_signal(
    filing=filing,
    model_version='test',
    signal_values={'rlds': 0.85, 'forward_pessimism': 0.72, 'insider_signal': 0.60}
)
assert result.signal_value == 0.25, f'Expected 0.25, got {result.signal_value}'
assert result.detail['triplet_confidence'] == 'full'
print('✅ CAS 1 (3/3): boost=0.25, confidence=full')

# CAS 2: 2 signaux élevés → boost = 0.15
result = _build_triplet_convergence_signal(
    filing=filing,
    model_version='test',
    signal_values={'rlds': 0.70, 'forward_pessimism': 0.10, 'insider_signal': 0.45}
)
assert result.signal_value == 0.15, f'Expected 0.15, got {result.signal_value}'
assert result.detail['triplet_confidence'] == 'strong'
print('✅ CAS 2 (2/3): boost=0.15, confidence=strong')

# CAS 3: 1 signal élevé → boost = 0.0
result = _build_triplet_convergence_signal(
    filing=filing,
    model_version='test',
    signal_values={'rlds': 0.70, 'forward_pessimism': 0.10, 'insider_signal': 0.05}
)
assert result.signal_value == 0.0, f'Expected 0.0, got {result.signal_value}'
assert result.detail['triplet_confidence'] == 'weak'
print('✅ CAS 3 (1/3): boost=0.0, confidence=weak')

# CAS 4: 0 signal élevé → boost = 0.0
result = _build_triplet_convergence_signal(
    filing=filing,
    model_version='test',
    signal_values={'rlds': 0.10, 'forward_pessimism': 0.05, 'insider_signal': 0.02}
)
assert result.signal_value == 0.0
assert result.detail['triplet_confidence'] == 'none'
print('✅ CAS 4 (0/3): boost=0.0, confidence=none')

# CAS 5: Signaux manquants (None) → pas de crash
result = _build_triplet_convergence_signal(
    filing=filing,
    model_version='test',
    signal_values={'rlds': None, 'forward_pessimism': None, 'insider_signal': None}
)
assert result.signal_value == 0.0
print('✅ CAS 5 (None): pas de crash, boost=0.0')

print()
print('🎉 TOUS LES TESTS PASSENT !')
"
```

### Test 5: Vérifier en BD après exécution

```sql
-- Vérifier que le signal est bien stocké
SELECT 
    ss.filing_id,
    ss.signal_name,
    ss.signal_value,
    ss.detail->>'triplet_confidence' as confidence,
    ss.detail->>'triplet_signals_elevated' as elevated_count
FROM signal_scores ss
WHERE ss.signal_name = 'triplet_convergence_signal'
ORDER BY ss.computed_at DESC
LIMIT 10;
```

---

## Exemples concrets

### Cas réel 1: NKLA (Nikola) — Triple convergence

```python
# Signaux d'entrée:
signal_values = {
    "rlds": 0.85,               # ✅ > 0.25 → Le texte a beaucoup changé
    "forward_pessimism": 0.72,   # ✅ > 0.25 → Direction très pessimiste
    "insider_signal": 0.60,      # ✅ > 0.15 → Dirigeants vendent
}

# Résultat:
triplet_convergence_signal = {
    "signal_value": 0.25,        # Boost MAXIMUM
    "detail": {
        "triplet_signals_elevated": 3,
        "triplet_confidence": "full",
        "interpretation": "Convergence maximale: anomalie texte + pessimisme + ventes insiders"
    }
}
```

### Cas réel 2: AAPL (Apple) — Convergence partielle

```python
signal_values = {
    "rlds": 0.30,               # ✅ > 0.25 → Léger changement de texte
    "forward_pessimism": 0.10,   # ❌ < 0.25 → Direction confiante
    "insider_signal": 0.45,      # ✅ > 0.15 → Quelques ventes d'insiders
}

# Résultat:
triplet_convergence_signal = {
    "signal_value": 0.15,        # Boost modéré
    "detail": {
        "triplet_signals_elevated": 2,
        "triplet_confidence": "strong",
    }
}
```

### Cas réel 3: NVDA (Nvidia) — Pas de convergence

```python
signal_values = {
    "rlds": 0.12,               # ❌ < 0.25 → Texte stable
    "forward_pessimism": 0.08,   # ❌ < 0.25 → Direction optimiste
    "insider_signal": 0.05,      # ❌ < 0.15 → Pas de ventes suspectes
}

# Résultat:
triplet_convergence_signal = {
    "signal_value": 0.0,         # Pas de boost
    "detail": {
        "triplet_signals_elevated": 0,
        "triplet_confidence": "none",
    }
}
```

---

## Troubleshooting

### ❌ Erreur: `'triplet_convergence_signal' not found in catalog`

**Cause**: Le signal n'a pas été ajouté à `signals/catalog.py`

**Solution**: Ajouter la `SignalDefinition` dans `SIGNAL_DEFINITIONS` (voir section Fichier 2)

### ❌ Erreur: `ImportError` ou `AttributeError`

**Cause**: La fonction `_build_triplet_convergence_signal` n'est pas définie

**Solution**: Vérifier qu'elle est bien ajoutée dans `composite_engine.py` AVANT la fonction `compute_composite_signals` qui l'appelle, ou après `_build_convergence_signal`

### ⚠️ Le signal vaut toujours 0.0

**Cause possible 1**: Les signaux rlds/forward_pessimism/insider_signal n'existent pas encore pour ce filing

```bash
python -c "
from app.db.session import SessionLocal
from app.db.models.signal_score import SignalScore

session = SessionLocal()
for name in ['rlds', 'forward_pessimism', 'insider_signal']:
    count = session.query(SignalScore).filter(
        SignalScore.signal_name == name,
        SignalScore.signal_value.isnot(None)
    ).count()
    print(f'{name}: {count} filings avec valeur')
session.close()
"
```

**Cause possible 2**: Les seuils sont trop élevés pour les données

```bash
python -c "
from app.db.session import SessionLocal
from app.db.models.signal_score import SignalScore
from sqlalchemy import func

session = SessionLocal()
for name, threshold in [('rlds', 0.25), ('forward_pessimism', 0.25), ('insider_signal', 0.15)]:
    above = session.query(func.count(SignalScore.id)).filter(
        SignalScore.signal_name == name,
        SignalScore.signal_value >= threshold
    ).scalar()
    total = session.query(func.count(SignalScore.id)).filter(
        SignalScore.signal_name == name,
        SignalScore.signal_value.isnot(None)
    ).scalar()
    pct = (above/total*100) if total > 0 else 0
    print(f'{name}: {above}/{total} au-dessus du seuil {threshold} ({pct:.1f}%)')
session.close()
"
```

### ⚠️ Le nouveau signal n'apparaît pas dans signal_scores

**Cause**: Le pipeline composite n'a pas été relancé après la modification

**Solution**: Relancer les signaux composites pour un filing :

```bash
python run_signals.py --filing-id 123
```

Ou recalculer les composites seuls :

```bash
python -c "
from signals.composite_engine import compute_and_store_composite_signals
compute_and_store_composite_signals(filing_id=123)
print('✅ Done')
"
```

---

## 📊 Checklist d'implémentation

### Préparation
- [ ] ÉTAPE 1 (Autoencoder) complétée et vérifiée
- [ ] Signaux rlds, forward_pessimism, insider_signal existent en BD

### Implémentation
- [ ] Ajouter `_build_triplet_convergence_signal()` dans `composite_engine.py`
- [ ] Appeler la fonction dans `compute_composite_signals()`
- [ ] Ajouter `triplet_convergence.to_dict()` au return
- [ ] Ajouter la définition dans `catalog.py`

### Tests
- [ ] Import OK: `from signals.composite_engine import compute_composite_signals`
- [ ] Catalog OK: `get_signal_definition('triplet_convergence_signal')` retourne non-None
- [ ] Test unitaire: 3/3 élevés → boost=0.25
- [ ] Test unitaire: 2/3 élevés → boost=0.15
- [ ] Test unitaire: 1/3 ou 0/3 → boost=0.0
- [ ] Test unitaire: signaux None → pas de crash
- [ ] Test BD: signal stocké dans signal_scores après `run_signals.py`

### Après complétion
- [ ] ✅ Étape 2 complétée
- [ ] ✅ Prêt pour ÉTAPE 3 (Sentinel Quality Monitoring)

---

## 🔗 Fichiers de référence

| Fichier | Rôle |
|---|---|
| `signals/composite_engine.py` | Fichier principal à modifier |
| `signals/catalog.py` | Ajouter la définition du signal |
| `signals/policies.py` | Seuils et poids (lecture seule) |
| `signals/common.py` | Utilitaires comme `clip01()` |
| `signals/composite_repo.py` | Lecture des signaux depuis la BD |
| `signals/signal_repo.py` | Écriture des signaux en BD |

---

**Version**: 1.0  
**Date**: 27 Avril 2026  
**Status**: ✅ Guide complet — Prêt pour implémentation
