# Infos — choix du cas d'usage (cancer du sein vs drépanocytose)

Notes de travail, à exploiter pour la rédaction du
mémoire (introduction, problématique, état de l'art médical). Date : 2026-09-21/22.

## 1. Question de départ

Le projet couvre deux maladies dans le panel de gènes (`ALL_GENES`,
`src/ingestion/config.py`) : le cancer du sein héréditaire (12 gènes) et la drépanocytose /
modificateurs HbF (6 gènes). Question posée : laquelle privilégier comme cas d'usage
principal du mémoire, sachant qu'un bioinformaticien a déjà transmis une ressource sur le
cancer du sein ?

## 2. Recommandation (angle data engineering)

**Cancer du sein en cas d'usage principal, drépanocytose en second panel** (l'architecture —
un DAG par panel — permet d'en garder plusieurs sans coût supplémentaire).

Arguments en faveur du cancer du sein :

- **Richesse des données.** Gènes (BRCA1, BRCA2, PALB2, ATM, etc.) très représentés dans
  ClinVar : beaucoup de variants, statuts de revue élevés (panels d'experts type ENIGMA),
  reclassifications fréquentes, annotations HPO/MedGen abondantes. Alimente bien les
  documents RAG (historique de reclassification, statuts de revue) et l'étoile analytique du
  sous-projet D.
- **Évaluation du RAG plus solide.** Questions à réponse vérifiable dans ClinVar (ex. « ce
  variant BRCA1 est-il pathogène ? »).
- **Volume.** Le cancer du sein représente l'essentiel des ~97 000 variants du panel.
- **Ressource externe disponible** : le document du bioinformaticien (section 4) sert de base
  à la partie médicale du mémoire et de point de validation.

Limites de la drépanocytose comme cas d'usage principal :

- Maladie quasi monogénique (HBB, p.Glu6Val) : peu de variance à exploiter.
- Gènes modificateurs HbF (BCL11A, HBS1L, MYB) = loci GWAS ; HBS1L et MYB n'ont **aucune**
  annotation HPO (constaté sur les vraies données du panel).
- ClinVar sous-représente les populations africaines — limite scientifique réelle, mais aussi
  un angle de discussion possible si le mémoire vise un contexte africain.

**Nuance à trancher par l'auteur :** si le mémoire vise explicitement un contexte de santé
publique africain, la drépanocytose devient plus originale et plus pertinente comme fil
rouge, au prix d'un jeu de données plus pauvre à assumer comme limite. À arbitrer selon
l'angle du mémoire (technique/pipeline vs santé publique/contexte local) et les critères de
l'encadrement.

**Aucun impact sur l'architecture technique en cours** (sous-projet D, en pause) : la spec
Gold reste identique quel que soit le panel retenu.

## 3. Document transmis par le bioinformaticien

Fichier source : `CANCER DU SEIN CHEZ LA FEMME_Diagnostic_et_Approche_thérapeutique.docx`
(racine du projet).

### 3.1 Diagnostic du cancer du sein — étapes

1. **Analyse histochimique et immunohistochimie (IHC) sur biopsie**
   - Étape 1 : prélèvement sur le tissu mammaire suspect (biopsie), examen histologique
     (anapath) pour confirmer le caractère malin ou non de la tumeur.
   - Étape 2 : évaluation des biomarqueurs de base :
     - récepteurs hormonaux (RH) : progestérone et œstrogène,
     - HER2 (Human Epidermal Growth Factor Receptor 2),
     - Ki-67 (indice de prolifération, évalue l'agressivité de la tumeur).

2. **Classification moléculaire en 3 types** (sur la base de ces biomarqueurs — donnée
   clinique/tumorale, distincte de la classification ClinVar des variants germinaux) :
   - **Type 1 — Hormono-dépendant (RH+)** : ~70 % des cas, le plus fréquent, très sensible à
     l'hormonothérapie.
   - **Type 2 — HER2 amplifié (HER2+)** : 10-15 % des cas, sensible aux anticorps et à la
     thérapie ciblée.
   - **Type 3 — Triple négatif (RH-, HER2-)** : pas de cible thérapeutique particulière ;
     chimiothérapie, thérapie ciblée, etc.

### 3.2 Médecine personnalisée et biologie moléculaire

- Stade local : pas de biologie moléculaire nécessaire, sauf histoire familiale.
- Stade métastatique : large panel moléculaire.
- **Gènes de prédisposition génétique héréditaire** : 2-5 % des cas en général, jusqu'à 15 %
  dans les triple négatifs. Principales mutations recherchées : **BRCA1** et **BRCA2**, via
  biologie moléculaire NGS sur prélèvement sanguin (parmi une dizaine de gènes).
- **Gènes de prédisposition non génétique** (marqueurs somatiques, recherchés sur biopsie
  tumorale et prise de sang) : **TP53** (responsable de nombreux cancers), **ESR1** (mutation
  sur le récepteur des hormones — noté « ESRA » dans le document), **PIK3CA** (enzyme
  intracellulaire activant les voies de réplication — noté « Pik3A »).

### 3.3 Contexte local (Institut Pasteur de Dakar)

- L'analyse BRCA1/BRCA2 est actuellement **sous-traitée en France** (laboratoire Biomnis),
  pour un coût global d'environ **400 000 FCFA** — jugé élevé par le bioinformaticien.
  → argument fort pour la problématique du mémoire (accès, coût, délai, dépendance à
  l'étranger pour l'interprétation de variants).
- Équipement mentionné : séquenceur de paillasse **Illumina MiSeq** (15 Go / 25 M reads /
  2×300 pb), avec panels disponibles : Immune Response (24 échantillons), Focus Panel 2 (48),
  BRCA Somatic (80), BRCA Germline (96), Myeloid Panel 2 (11), Immune Repertoire (24).

## 4. Confrontation avec le panel de gènes du projet

Panel actuel (`BREAST_CANCER_GENES`, `src/ingestion/config.py:43-46`) : BRCA1, BRCA2, TP53,
PALB2, PTEN, CDH1, STK11, ATM, CHEK2, BARD1, RAD51C, RAD51D.

- **BRCA1, BRCA2, TP53** : déjà couverts par le panel — cohérent avec le document.
- **ESR1, PIK3CA** cités dans le document mais **volontairement hors périmètre** : ce sont
  des marqueurs **somatiques** (mutations acquises dans la tumeur, recherchées sur biopsie),
  pas des gènes de prédisposition **germinale héréditaire**. Ils relèvent d'une base type
  COSMIC / séquençage tumoral, pas de ClinVar germinal — domaine de données différent de
  celui du projet. Ne pas les ajouter au panel ; à mentionner dans le mémoire comme limite de
  périmètre assumée (le projet couvre le dépistage héréditaire germinal, pas le profilage
  somatique tumoral).

## 5. Pistes pour la rédaction du mémoire

- **Introduction/problématique** : coût et délai de l'analyse BRCA1/BRCA2 sous-traitée à
  l'étranger (Institut Pasteur Dakar → Biomnis France, ~400 000 FCFA) comme motivation
  concrète pour un outil d'aide à l'interprétation localisé.
- **État de l'art médical** : la classification en 3 types moléculaires (RH+/HER2+/triple
  négatif) et la distinction prédisposition héréditaire (BRCA1/2, germinale) vs marqueurs
  somatiques (TP53, ESR1, PIK3CA) — utile pour délimiter clairement le périmètre du projet
  (germinal héréditaire, source ClinVar) face à ce qu'il ne couvre pas (profilage tumoral
  somatique).
- **Limites à assumer explicitement** : sous-représentation des populations africaines dans
  ClinVar ; pour la drépanocytose (si retenue en second panel), pauvreté des annotations HPO
  sur les gènes modificateurs HbF (HBS1L, MYB).
