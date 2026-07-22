# Gènes de référence — Cancer du sein

> Périmètre : gènes pertinents pour l'interprétation de variants ADN (données germinales, ClinVar).
> Objectif : couverture complète et justifiée pour le système RAG.

---

## Point clé à retenir : germinal vs somatique

« Cancer du sein » recouvre **deux familles de gènes totalement différentes**. Il est essentiel de
choisir la bonne pour un système d'interprétation de variants ADN.

| | Gènes germinaux (héréditaires) | Gènes somatiques (tumeur) |
|---|---|---|
| Origine du variant | Hérité, présent dans **tout le corps** | Apparu **dans la tumeur** uniquement |
| Ce qu'il indique | **Risque / prédisposition** au cancer | Comportement de la tumeur, choix du **traitement** |
| Base de données | **ClinVar** (classification ACMG) | COSMIC, dossiers oncologiques |
| Test concerné | Test de prédisposition héréditaire | Profilage tumoral (biopsie) |
| **Pertinent pour ton projet ?** | ✅ **OUI** — c'est exactement ce que tu interprètes | ❌ Non — autre paradigme, pas ClinVar/ACMG |

**Conclusion : « complet pour le cancer du sein » dans ton système = le panel COMPLET des gènes de
prédisposition germinale** (ceux des panels cliniques NCCN / ESMO). C'est la liste ci-dessous.
Les gènes somatiques (voir dernière section) constitueraient un autre projet.

---

## Critères de sélection des gènes (règle de décision)

Un gène est **inclus** dans le périmètre du projet si — et seulement si — il remplit les **4 critères**
suivants. Cette règle est ce qui rend la sélection objective et défendable en soutenance.

| # | Critère d'inclusion | Justification par rapport au projet |
|---|---------------------|-------------------------------------|
| 1 | **Gène de prédisposition GERMINALE** (variant hérité) | Le système interprète le séquençage ADN constitutionnel d'un patient, pas une biopsie tumorale. |
| 2 | **Présent dans ClinVar avec classification ACMG** | ClinVar est l'unique source de vérité du RAG. Un gène sans variants classés n'a rien à indexer. |
| 3 | **Inclus dans les panels cliniques de référence** (NCCN, ESMO) | Garantit la pertinence médicale réelle pour le biologiste utilisateur. |
| 4 | **Volume de variants suffisant pour le retrieval** | Un gène avec trop peu de variants dégrade la qualité du RAG (rien à récupérer). |

Un gène qui échoue à **au moins un** de ces critères est **exclu**, et la section « Gènes exclus »
ci-dessous documente précisément lequel.

---

## 1. Gènes à HAUTE pénétrance

Risque élevé de cancer du sein. Base des tests génétiques de prédisposition.

| Gène | Localisation | Syndrome / rôle | Variants ClinVar (ordre de grandeur) | Statut |
|------|--------------|-----------------|--------------------------------------|--------|
| **BRCA1** | 17q21.31 | Réparation ADN (recombinaison homologue). Syndrome sein-ovaire (HBOC). | ~4 000 | ✅ Déjà choisi |
| **BRCA2** | 13q13.1 | Réparation ADN. Syndrome sein-ovaire (HBOC). | ~6 000 | ✅ Déjà choisi |
| **TP53** | 17p13.1 | Suppresseur de tumeur. Syndrome de Li-Fraumeni. | ~10 000 | ✅ Déjà choisi |
| **PALB2** | 16p12.2 | Partenaire de BRCA2 dans la réparation ADN. | ~500 | ✅ Déjà choisi |
| **PTEN** | 10q23.31 | Suppresseur de tumeur. Syndrome de Cowden. | ~3 000 | ✅ Retenu |
| **CDH1** | 16q22.1 | E-cadhérine. Cancer gastrique diffus héréditaire + **cancer du sein lobulaire**. | ~2 000 | ✅ Retenu |
| **STK11** | 19p13.3 | Syndrome de Peutz-Jeghers. | ~500 | ✅ Retenu |

---

## 2. Gènes à pénétrance MODÉRÉE

Risque augmenté (typiquement 2-4×). Inclus dans tous les panels NGS cliniques modernes.

| Gène | Localisation | Rôle | Variants ClinVar | Statut |
|------|--------------|------|------------------|--------|
| **ATM** | 11q22.3 | Checkpoint ADN. | ~2 000 | ✅ Déjà choisi |
| **CHEK2** | 22q12.1 | Checkpoint kinase. Variant c.1100delC mondialement référencé. | ~1 500 | ✅ Déjà choisi |
| **BARD1** | 2q35 | Partenaire de BRCA1. | ~800 | ✅ Retenu |
| **RAD51C** | 17q22 | Réparation ADN (recombinaison homologue). | ~800 | ✅ Retenu |
| **RAD51D** | 17q12 | Réparation ADN (recombinaison homologue). | ~500 | ✅ Retenu |
| **NF1** | 17q11.2 | Neurofibromatose type 1 ; risque modéré de cancer du sein. | ~5 000 | ⬜ À considérer |

---

## Synthèse : périmètre RETENU (décision finale)

**Décision : panel germinal complet — 12 gènes de prédisposition.**
Le système couvre l'intégralité des gènes de prédisposition héréditaire au cancer du sein présents
dans ClinVar et inscrits aux panels cliniques NCCN/ESMO. Aucun gène de prédisposition n'est écarté.

- **Haute pénétrance (7) :** BRCA1, BRCA2, TP53, PALB2, PTEN, CDH1, STK11
- **Pénétrance modérée (5) :** ATM, CHEK2, BARD1, RAD51C, RAD51D
- **Optionnel (non compté) :** NF1 (risque modéré, ajout possible)

Cette décision donne la **ligne de défense la plus solide** : *« J'inclus tous les gènes de
prédisposition héréditaire présents dans ClinVar ; j'exclus uniquement les gènes somatiques,
qui relèvent d'un autre paradigme. »*

---

## Liste finale recommandée (à indexer)

```
# --- Haute pénétrance ---
BRCA1
BRCA2
TP53
PALB2
PTEN        # ajout
CDH1        # ajout
STK11       # ajout
# --- Pénétrance modérée ---
ATM
CHEK2
BARD1       # ajout
RAD51C      # ajout
RAD51D      # ajout
NF1         # optionnel
```

---

## Gènes EXCLUS et justification (à défendre en soutenance)

Cette section documente les gènes « cancer du sein » que le projet **n'indexe pas**, et **pourquoi**.
Elle est conçue pour répondre directement à la question du jury : *« Pourquoi ces gènes et pas
d'autres ? »*

### Catégorie A — Gènes somatiques (drivers de la tumeur) → EXCLUS

**Échec du critère n°1** (ce ne sont pas des gènes de prédisposition germinale).

| Gène | Ce qu'il est | Pourquoi exclu du projet |
|------|--------------|--------------------------|
| **PIK3CA** | Driver somatique le plus fréquent du cancer du sein | Mutation acquise **dans la tumeur**, pas héritée. Sert à choisir une thérapie ciblée, pas à évaluer un risque héréditaire. |
| **ESR1** | Résistance à l'hormonothérapie (tumeur) | Variant somatique acquis sous traitement. Absent de la logique ClinVar/ACMG. |
| **ERBB2 (HER2)** | Amplification tumorale, cible du trastuzumab | Marqueur tumoral, déterminé par profilage de la tumeur, pas par le génome constitutionnel. |
| `GATA3`, `MAP3K1`, `AKT1`, `RB1`, `CBFB`, `MAP2K4` | Autres drivers somatiques | Même raison : génome de la tumeur, autre source de données (COSMIC), autre paradigme d'interprétation. |

**Justification synthétique (formulation soutenance) :**
> « Ces gènes appartiennent au génome **somatique** de la tumeur. Mon système interprète le génome
> **constitutionnel** (germinal) du patient à partir de ClinVar et des critères ACMG. Les inclure
> reviendrait à mélanger deux paradigmes d'interprétation incompatibles et deux sources de données
> différentes. Ils relèveraient d'un module distinct de profilage tumoral, identifié comme
> perspective d'évolution. »

### Catégorie B — Gènes germinaux non retenus → AUCUN

**Décision prise : le panel germinal complet est inclus (12 gènes).**
Aucun gène de prédisposition héréditaire au cancer du sein n'est écarté. La seule exclusion du
projet est la catégorie A (gènes somatiques). C'est ce qui garantit qu'un biologiste interrogeant
un variant de prédisposition trouvera toujours le gène concerné dans le système.

*(NF1 reste optionnel : risque modéré et moins central ; son ajout ne change pas la ligne de défense.)*

---

## Tableau de synthèse pour la soutenance

| Décision | Gènes | Justification en une phrase |
|----------|-------|-----------------------------|
| ✅ **Inclus** | BRCA1, BRCA2, TP53, PALB2, PTEN, CDH1, STK11, ATM, CHEK2, BARD1, RAD51C, RAD51D | Gènes de prédisposition germinale, présents dans ClinVar, inscrits aux panels cliniques NCCN/ESMO. |
| ❌ **Exclus — somatiques** | PIK3CA, ESR1, ERBB2/HER2, GATA3, AKT1… | Mutations de la tumeur, non héritées, hors du cadre ClinVar/ACMG de mon système. |
| 🔵 **Perspective** | Module de profilage tumoral | Extension future, source et logique d'interprétation distinctes. |
