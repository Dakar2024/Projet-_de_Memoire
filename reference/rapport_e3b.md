# Rapport E3b — Évaluation du pipeline de données

Spec : `docs/superpowers/specs/2026-10-23-sous-projet-e3b-evaluation-pipeline-design.md` (locale).
Critères fixés **avant** les mesures. Pile isolée `genomique-e3b` (spec § 3), jamais la principale.

| Niveau | État |
|---|---|
| 6 — Restauration | ✅ conforme ; un défaut du pipeline trouvé (D-E3b-1), **corrigé et revérifié** |
| 5 — Comportement en panne | ✅ six scénarios joués ; deux défauts trouvés et corrigés (D-E3b-2, D-E3b-3) ; réserve O-E3b-2 **levée** le 26/10 |
| 7a — Onze fiches (utilisateur) | grille pré-remplie (`reference/grille_justesse_e3b.md`), à cocher par l'utilisateur ; un défaut trouvé en la préparant (D-E3b-4), **corrigé** |
| 7b — 400 variants contre l'API ClinVar | ✅ 400/400 conformes, Wilson 95 % [99,05 ; 100] ; règle des maladies corrigée après mesure (P-E3b-1), les deux résultats donnés |
| Clôture (26/10/2026) | pile isolée démontée (`down -v`, `data/e3b` supprimé) ; pile principale saine, lac intact (97 210 documents, 97 192 variants) ; `evaluation.md` et `TODO.md` mis à jour |

---

## Niveau 5 — Comportement en panne (23 et 24/10/2026)

Pile isolée, restaurée au niveau 6. **Scénarios reformulés sur le mois en cours** : le 24/10/2026,
l'utilisateur a fixé la règle « le pipeline ne traite que le mois en cours, jamais un mois passé »
(commit f597ec0). P3 ne vise donc plus 2019 mais octobre avec `force`, P6 ne vise plus un
`bronze_to_silver` hors ordre mais le refus en amont. Mails reçus : ceux de la pile isolée, même
`ALERT_EMAIL`.

| # | Scénario | Provocation | Observé | Verdict |
|---|---|---|---|---|
| P1 | Conteneur tué en plein run | `docker kill` du scheduler isolé à 12:01:27 pendant `bronze_to_silver` (brca), redémarré à 12:02:40 | Les deux tâches en cours (`bronze_to_silver` brca, `ingest_refseq` sickle) marquées en échec à 12:02:15, réussies au 2ᵉ essai ; les deux runs vont au bout. Chaque table instantanée prend exactement 2 versions (une par panel, comme un run normal) : l'essai tué n'a rien commité. `clinvar_variant` reste v1, `gold/rag/documents` inchangé (R4). Deux mails de succès, aucun mail d'échec | ✅ |
| P2 | Disque saturé | Scheduler isolé avec un tmpfs de 1 Gio sur `data/external`, acquisition d'octobre `force` | « espace disque insuffisant dans /opt/projet/data/external : 1,0 Gio libres pour 2,0 Gio requis », **avant tout téléchargement** ; mais **4 essais en 15 min** au lieu d'un échec immédiat ; aucun événement d'Asset | ⚠️ D-E3b-3 |
| P3 | Source indisponible | Scheduler isolé derrière un proxy fermé (`HTTPS_PROXY=http://127.0.0.1:9`), archive retirée du cache, acquisition d'octobre `force` | ClinVar : `ProxyError` explicite, 4 essais en 15 min, mail d'échec « après 4 essais » ; aucun événement d'Asset ; aucun run de panel. HPO réussit sans réseau : un rejeu relit la release épinglée dans le manifest du mois (`v2026-09-01`) et le fichier en cache, voulu | ✅ |
| P4 | Archive tronquée | Bronze ClinVar d'octobre réécrit avec une ligne sur deux (9 223 698 → 4 611 849), panel brca sur octobre | `quality_check_silver` : « 42722 variant(s) courant(s) sur 93615 absent(s) de l'instantané du mois, soit 46 % — au-delà du seuil de 5 % » ; Gold non construit (versions inchangées), rien d'indexé, pas de mail de succès. Mais 4 essais du contrôle (D-E3b-3) et Silver instantané réécrit avec les données tronquées (O-E3b-2) | ✅ réserve |
| P5 | Double déclenchement | Trigger manuel sans date, octobre déjà publié | Mois résolu `2026-10-01` depuis l'heure de départ ; 6 tâches sautées par `skip_if_already_published` ; aucun événement d'Asset, aucun run de panel (7 s) | ✅ |
| P6 | Mois passé | `--logical-date 2026-09-10` sur l'acquisition ; `sources_date 2026-09-01` sur brca | Les deux refusés au 1er essai, 4 s : « … hors du mois en cours (2026-10) : le pipeline ne traite que le mois en cours » ; aucune ingestion. Avant la règle (23/10) : `bronze_to_silver` des deux panels refusait septembre (« contient déjà le mois »), 24 versions Delta inchangées — la garde reste en filet | ✅ |

### Défaut D-E3b-2 — panel lancé sur un mois sans sources partagées (corrigé)

**Observé le 23/10** : un run de panel sur un mois sans acquisition échouait dans `bronze_to_silver`
sur un `NoSuchKey` brut, après les ingestions NCBI et trois relances. **Corrigé** (f597ec0) :
`resolve_sources_date` vérifie d'abord que le bronze ClinVar et HPO du mois est complet, et échoue
sans relance (« lancer d'abord dag_acquisition_sources pour ce mois »).

### Défaut D-E3b-3 — erreurs permanentes relancées (corrigé)

**Observé** (P2, P4, et le 24/10 à 01:24 quand le disque C: était plein) : `ensure_free_space`
lève une `ConfigurationError` documentée « non relancée », et `quality_check_silver` une
`SilverQualityError` ; aucune des tâches qui les appellent (`download_clinvar_bulk`,
`download_hpo_files`, `quality_check_silver`, et de même `quality_check_gold`) ne les convertit en
`AirflowFailException`. Chaque relance refait le même constat : 15 min perdues, et le mail d'échec
dit « après 4 essais, erreur peut-être passagère » au lieu de « corriger la cause ».

**Correction** (24/10/2026, avec l'accord de l'utilisateur) : ces quatre tâches convertissent leur
erreur en `AirflowFailException`, message conservé. Tests d'abord, rouges sur l'ancien code.
**Revérifié en réel** : P2 rejoué à 15:19, échec des deux téléchargements au **1er essai**, run
terminé en 13 s.

### Observation O-E3b-1 — run manuel avant `start_date`

Le 23/10, `--logical-date 2019-01-10` donnait un run « réussi » sans aucune tâche : Airflow ne crée
pas de tâche avant le `start_date` du DAG (2026-01-01). Sans effet sur les données (rien n'est
ingéré, conforme à la règle du mois en cours), mais sans message.

### Observation O-E3b-2 — le Silver n'est pas protégé par son propre contrôle (levée)

Le contrôle Silver bloque le Gold, pas le Silver : `bronze_to_silver` a déjà remplacé les tables
instantanées du panel par les données tronquées (v7 → v8). L'application et le RAG lisent le Gold,
resté sain ; le Silver reste faux jusqu'au prochain run correct (`procedure_reprise.md` § 5.1 :
réacquérir le mois avec `force`).

**Levée** (26/10/2026, option « contrôler avant d'écrire » choisie par l'utilisateur parmi trois) :
- **Fonction pure partagée.** Les contrôles deviennent une fonction pure, `find_silver_errors`.
  `bronze_to_silver` l'applique aux tables **candidates**, en mémoire, avant la première écriture.
  L'état de `clinvar_variant` après la fusion SCD2 est reconstruit sans rien écrire, avec la même
  détection des changements que l'écriture. En cas d'échec : « Silver non publié, rien n'a été
  écrit », échec définitif sans relance.
- **Défense en profondeur.** `quality_check_silver` refait les mêmes contrôles sur les tables
  publiées.
- **Tests d'abord.** Trois tests étaient rouges sur l'ancien code :
  - une archive tronquée de moitié ne change la version Delta d'aucune des 10 tables ;
  - un premier run sans variant ne crée aucune table ;
  - le DAG transforme le refus en échec définitif.

  La graine des tests de `bronze_to_silver` a reçu une vraie notice MedGen : sans elle,
  `medgen_mim` et `medgen_inheritance` sortaient vides, ce que le contrôle refuse désormais.
- **Revérifié sur un lac jetable.** Vrai bronze d'octobre, panel sickle. Silver publié, puis
  bronze ClinVar tronqué comme en P4 (9 223 698 → 4 611 849 lignes) : refusé, « 1470 variant(s)
  courant(s) sur 3577 absent(s) de l'instantané du mois, soit 41% ». Versions Delta inchangées sur
  les 10 tables, contrôle d'après publication toujours vert.

**Limite restante** : les 10 écritures ne forment pas une transaction, Delta n'en offre pas entre
tables. Un plantage au milieu laisse un Silver mixte : `quality_check_silver` le bloque avant le
Gold, et le rejeu du mois le répare.

---

## Niveau 6 — Restauration (23/10/2026)

### Déroulé

| Étape | Heure (UTC) | Détail |
|---|---|---|
| Copie | 15:01 | `~/sauvegardes-genomique/2026-10-23-1501` ; la pile principale n'a rien exécuté depuis (dernier run terminé à 13:38), une copie plus fraîche aurait été identique |
| Restauration | — | `scripts/restaurer.sh --pile genomique-e3b`, 2 min 16, sur une pile isolée démarrée vide |
| Fidélité | — | `scripts/comparer_piles.sh` : conforme, 1 min |
| Pile principale arrêtée | 19:06:00 | D7 : mesures sans contention |
| Rejeu forcé d'octobre | 19:06:29 | `--logical-date 2026-10-20 --conf '{"force": true}'` |
| Fin des deux panels | 19:16:54 | sickle en dernier |
| Pile principale redémarrée | après les relevés | 12 services sains |

### Critères

| # | Critère | Mesuré | Verdict |
|---|---|---|---|
| R1 | Restauration fidèle | Base Airflow (10 runs, 83 tâches, empreintes), base RAG (97 210 documents, vecteurs, index, droits, 10 plus proches voisins), 236 objets octet pour octet, 24 tables Delta relues | ✅ |
| R2 | Le pipeline tourne sur la pile restaurée | Acquisition 2 min 15, brca 5 min 50, sickle 8 min 09 ; toutes les tâches au premier essai ; aucun e-mail d'échec | ✅ |
| R3 | Le rejeu est vu comme un rejeu | Un seul événement d'Asset nouveau (n° 3, 19:08:44) ; `skip_if_already_published` laisse passer grâce à `force` ; `notify_catch_up` sauté (run manuel) | ✅ |
| R4 | Sources versionnées identiques | Bronze `clinvar` (9,2 M lignes) et `hpo` identiques hors colonnes techniques ; `silver/clinvar_variant` **v1 → v1**, aucune nouvelle version | ✅ |
| R5 | Écarts des sources non versionnées, expliqués | Seul MedGen bouge (bronze brca 45 lignes, sickle 17 ; Silver `medgen_concept` 62 = 45 + 17, colonne `conceptmeta_xml` seule : la notice servie par NCBI le jour de l'appel). NCBI Gene et RefSeq identiques. **Mais** `gold/analytique/dim_disease` change de 13 lignes **sans lien avec MedGen** : défaut D-E3b-1 | ✅ après correction de D-E3b-1 |
| R6 | Gold et index suivent | `gold/rag/documents` **v1 → v1** (aucune écriture) ; indexation : 0 à vectoriser, 0 à supprimer, 93 627 + 3 583 inchangés, canari 1,000000 | ✅ |
| R7 | Volumes (< 5 % de la référence d'octobre) | `clinvar_variant` 97 192 (93 615 brca, 3 577 sickle) : 0 % ; `clinvar_variant_disease` 171 141 ; `gold/rag/documents` 97 210 | ✅ |
| R8 | Ressources | Pic mémoire du scheduler **1 022 Mio** (114 relevés à 5 s, pic à 19:08:35, pendant `raw_to_bronze_shared`), seuil 2,5 Gio ; durées dans les références du protocole (§ 9) | ✅ |

Durées comparées au § 9 du protocole (secondes) :

| Tâche | Référence | brca | sickle |
|---|---|---|---|
| `bronze_to_silver` | 10 (brca), 5 (sickle) | 8 | 6 |
| `silver_to_gold_rag` | 15 (brca) | 6 | 2 |
| `silver_to_gold_analytique` | 3 (brca) | 3 | 3 |
| `quality_check_gold` | 1 | 2 | 2 |
| Panel complet | 8 à 12 min | 5 min 50 | 8 min 09 |

`ingest_medgen` domine (260 s brca, 130 s sickle) : appels NCBI à débit limité, pool à un créneau.

**Réserve sur R8** : un relevé toutes les 5 s peut manquer un pic bref. Le protocole citait 2 Go mesurés
sur la conversion ClinVar ; la valeur relevée ici est deux fois plus basse. Elle reste une borne
inférieure du vrai pic.

### Défaut D-E3b-1 — `dim_disease` non déterministe, avec perte d'identifiants

**Observé** : sur le rejeu, 13 CUI de `gold/analytique/dim_disease` changent d'identifiants OMIM
(9), Orphanet (5) ou MONDO (11). Exemple : `C0024623` « Gastric cancer » avait OMIM 613659 et
MONDO:0001056, il n'en a plus aucun après le rejeu.

**Cause** (code, puis données) : ces identifiants viennent de `phenotypeids` de ClinVar, source
versionnée dont le bronze est identique. Dans `clinvar_variant_disease`, 17 des 19 couples
(CUI, panel) concernés ont **plusieurs jeux d'identifiants sous le même nom de maladie** : pour
`C0024623`, une ligne porte OMIM et MONDO, une autre aucun. `silver_to_gold_analytique` trie par
`disease_name` puis garde la première ligne par CUI : entre lignes de même nom, le choix dépend de
l'ordre des lignes, que `_build_clinvar_variant_disease` ne garantit pas (`unique(keep="first")`
sans `maintain_order`). Le commentaire du code (« stable d'un run à l'autre ») est faux dans ce cas.

**Conséquences** : un rejeu peut remplacer des identifiants réels par des valeurs nulles, sans
erreur ni contrôle qui le signale ; deux runs sur les mêmes données ne donnent pas le même Gold
analytique. Le Gold RAG n'est pas touché (`documents` identique).

**Correction** (23/10/2026, avec l'accord de l'utilisateur) : `dim_disease` agrège par (CUI, panel)
au lieu de garder une ligne. Le nom retenu est le premier non nul par ordre alphabétique (un nom nul
passait devant au tri) ; les identifiants sont réunis **entre les seules lignes de ce nom**, plus
petite valeur non nulle : jamais l'identifiant d'une maladie sous le nom d'une autre.

Tests d'abord, rouges sur l'ancien code : le cas « Gastric cancer » dans les deux ordres ; vingt
permutations des lignes d'entrée donnent la même dimension ; pas de mélange de noms ; nom réel
préféré à un nom nul ; CUI aux noms tous nuls conservé.

**Revérifié sur les données réelles** (Silver rejoué de la pile isolée, `silver_to_gold_analytique`
lancé deux fois sur les deux panels) :

| Contrôle | Résultat |
|---|---|
| Deux passes successives | `dim_disease` identique |
| Contre la copie d'avant le rejeu (ancien code, run du 21/10) | 442 CUI, aucun disparu, aucun nom changé |
| Identifiants perdus ou modifiés | 0 |
| Identifiants **récupérés** (déjà perdus par le run du 21/10) | OMIM 8, Orphanet 7, MONDO 18 |
| `C0024623` « Gastric cancer » | OMIM 613659, MONDO:0001056, dans les deux panels |

Le Gold analytique de la pile principale garde l'ancienne dimension jusqu'au prochain run de panel.

Sorties : `data/experiments/e3b/ecarts_rejeu.txt`, `data/experiments/e3b/memoire.csv`.

---

## Niveau 7b — 400 variants contre l'API ClinVar (24/10/2026)

**Ce que 7b prouve, et ce qu'il ne prouve pas.** Il vérifie **nos transformations** (lecture du
fichier mensuel, filtres de panel, jointures, HGVS, éclatement des maladies) contre une autre voie
d'accès aux mêmes données, les E-utilities. Il ne vérifie pas ClinVar lui-même, puisque la source
est la même : c'est le rôle de la lecture humaine de 7a.

**Tirage** (`scripts/verifier_justesse.py --tirage`) : 400 variants courants du Silver d'octobre
(`valid_from` 2026-10-01), graine 20261023, au prorata des panels : 385 brca sur 93 615, 15 sickle
sur 3 577. Trié par `variationid` avant le tirage, donc indépendant de l'ordre de lecture Delta ;
figé dans `data/experiments/e3b/tirage.json`.

L'échantillon contient les cas difficiles :
- **dbSNP et dates** : 64 variants sans dbSNP (`-1`), 12 sans date d'évaluation ;
- **classification** : 11 sans classification germinale (`-`), 24 revus par un panel d'experts,
  9 sans critères ;
- **maladies** : 20 sans maladie, 64 avec trois maladies ou plus ;
- **forme** : 1 variant multi-gènes, 3 noms génomiques (`NC_`), 51 délétions.

**Comparaison** (`--comparer`, scheduler principal, lecture seule du lac, aucun run en cours) :
- les **cinq premiers champs** viennent d'`esummary` par lots de 200 ;
- les **maladies** viennent du XML VCV d'`efetch` (`rettype=vcv`) par lots de 20 ;
- durée : 21 s, en 22 appels.

Le code de comparaison est pur (`src/evaluation/clinvar_agreement.py`) et testé sur des fiches
réelles mises en fixtures.

| Champ | Règle | Écarts |
|---|---|---|
| Nom HGVS | `name` = `title`, au caractère près | 0 |
| Signification | égalité ; `-` chez nous = vide dans l'API (piège 3) | 0 |
| Statut de revue | idem | 0 |
| Date d'évaluation | API ≥ nôtre ; absente des deux côtés = égal | 0 |
| dbSNP | le nôtre ∈ ceux de l'API ; `-1` = aucun dans l'API | 0 |
| Maladies | les nôtres ⊆ conditions des RCV de la fiche, `not provided` et `not specified` exclus | 0 |

**Résultat : 400 conformes sur 400**, aucune fiche absente, aucune mise à jour postérieure.
Intervalle de Wilson à 95 % : [99,05 % ; 100 %]. Le taux d'erreur de nos transformations sur les
variants courants est donc, avec 95 % de confiance, inférieur à 1 %.

La règle du piège 1 (mise à jour postérieure) est testée mais n'a pas servi. Il n'y a que trois
semaines entre l'archive d'octobre et l'API : aucune date d'évaluation n'a bougé dans l'échantillon.

### Correction de protocole P-E3b-1 — les maladies comparées au mauvais champ

**Règle fixée d'avance** : nos maladies ⊆ `germline_classification.trait_set` de l'esummary.

**Mesure avec cette règle** : 339 conformes, 61 écarts, soit 84,75 %, Wilson [80,9 ; 87,9].
- **61 écarts sur les maladies.** Des maladies présentes chez nous manquent dans l'API. Exemple :
  125855, dont la date est identique des deux côtés, a chez nous « Breast-ovarian cancer, familial,
  susceptibility to, 1 », absente du `trait_set`.
- **11 écarts sur la signification et le statut.** Ce sont des variants sans classification
  germinale : `-` dans le fichier, chaîne vide dans l'API. C'était un défaut du comparateur (la
  sentinelle n'était pas normalisée), corrigé tests d'abord. Ces 11 variants étaient déjà comptés
  dans les 61.

**Cause**, établie avant tout changement de la règle :
- Le README de ClinVar (`tab_delimited/README`) dit que `PhenotypeList` liste les maladies
  **par RCV** : « the sets of names per RCV are separated by a pipe ». Il y inclut le contexte des
  données fonctionnelles.
- Le `trait_set` de l'esummary ne garde que les maladies de la classification **germinale
  agrégée**. Les deux champs n'ont donc pas le même périmètre.
- Vérifié sur les 61 écarts, en lisant les conditions des RCV dans le XML VCV : **61 sur 61** sont
  entièrement inclus.

**Décision** (utilisateur, 24/10/2026) : comparer les maladies aux conditions des RCV, et donner
les deux résultats. Le détail de la mesure avec la règle d'origine est conservé dans
`data/experiments/e3b/comparaisons_regle_initiale.csv` et `resume_regle_initiale.json`.

Ce n'est pas un défaut du pipeline : le Silver reproduit fidèlement le fichier. C'est une précision
pour le RAG. La ligne « Associated conditions » du document d'un variant cite les maladies de ses
RCV, pas seulement celles de sa classification germinale. Une maladie citée ne veut donc pas dire
« classé pathogène pour cette maladie ».

Sorties : `data/experiments/e3b/tirage.json`, `comparaisons.csv`, `resume.json`.

---

## Niveau 7a — Onze fiches (préparation, 26/10/2026)

`scripts/verifier_justesse.py --grille` vérifie que les onze variants du protocole (§ 8.2) sont
dans le Gold d'octobre. Ils y sont tous, aucun remplacement. L'outil écrit ensuite
`reference/grille_justesse_e3b.md`, une fiche par variant :
- **nos valeurs** : les six éléments, lus dans le Silver ;
- **le document RAG** : son texte réel et son lien de citation ;
- **à cocher par l'utilisateur** : la grille du § 11, et les cinq sources annexes, pré-remplies
  avec nos valeurs.

Vérification automatique du § 8.4 sur les **97 210 documents** : 0 `rs-1`, 0 `None`,
0 `Last evaluated: -.`, 0 `Review status: -`.

### Défaut D-E3b-4 — un seul mode de transmission par maladie dans le document RAG (corrigé)

**Observé** en préparant la grille : le document du variant n° 11 (HBB, 1048666) écrit « beta
Thalassemia (inheritance: Autosomal dominant inheritance) ». MedGen donne pour C0005283 **deux**
modes : récessif et dominant (`silver/medgen_inheritance`). Le document n'en cite qu'un, et pas le
plus courant pour cette maladie.

**Cause** (code) : `silver_to_gold_rag.build_documents` construit
`dict(inheritance.select("cui", "mode_inheritance").iter_rows())`. Quand une maladie a plusieurs
modes, le `dict` ne garde que **le dernier** lu, donc un mode choisi par l'ordre des lignes. Le
Gold analytique, lui, les réunit triés (`silver_to_gold_analytique.py:117`, joints par « ; »). Les
deux couches se contredisent donc.

**Étendue** : 26 couples (CUI, panel) sur 104 ont plusieurs modes, et jusqu'à 22 292 variants
citent l'une de ces maladies. Le document en cite au plus cinq (`MAX_DISEASES`), le nombre de
textes réellement touchés est donc inférieur.

**Conséquences** :
- **pour le lecteur** : le RAG peut affirmer un mode de transmission partiel, voire trompeur ;
- **pour le pipeline** : le texte dépend de l'ordre des lignes, donc son empreinte aussi. Un
  ordre différent entraînerait des re-vectorisations inutiles.

**Correction** (26/10/2026, avec l'accord de l'utilisateur) : `build_documents` agrège les modes
par CUI, sans doublon ni valeur nulle, triés et joints par « ; ». C'est la règle de `dim_disease` :
les deux couches disent maintenant la même chose.

Tests d'abord : deux modes donnés dans les deux ordres produisent le même texte, avec les deux
modes. Ces deux tests étaient rouges sur l'ancien code. Un troisième test vérifie qu'un mode nul
est ignoré. Suite complète : 1 757 tests verts.

**Revérifié sur les données réelles** (documents reconstruits en mémoire depuis le Silver
d'octobre du lac principal, rien d'écrit) :
- **bêta-thalassémie** : n° 11 donne « beta Thalassemia (inheritance: Autosomal dominant
  inheritance; Autosomal recessive inheritance) » ;
- **étendue** : 22 149 documents changent de texte, 394 sickle et 21 755 brca, tous sur la seule
  ligne « Associated conditions ». Exemple : « Familial cancer of breast » n'affichait que
  « Non-Mendelian inheritance », MedGen donne aussi « Autosomal dominant inheritance ».

Le Gold RAG de la pile principale garde l'ancien texte jusqu'au prochain run de panel, qui
re-vectorisera ces documents : leur empreinte change. La grille 7a montre donc encore l'ancien
document du n° 11.

