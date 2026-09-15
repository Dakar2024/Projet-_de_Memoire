# Architecture en quatre couches et formats de stockage — Design

**Date :** 2026-09-15
**Statut :** validé par l'utilisateur, en attente de relecture de ce document
**Amende :** `2026-09-04-pipeline-medaillon-airflow-minio-design.md`

---

## 1. Objet

Ce document amende la spec du 2026-09-04 sur quatre points décidés depuis :

1. le médaillon passe de trois à **quatre couches** : `raw`, `bronze`, `silver`, `gold` ;
2. le moteur de transformation est choisi : **Polars** ;
3. chaque couche reçoit un **format de stockage** justifié par les données ;
4. la couche Gold se sépare en **`gold/rag`** et **`gold/analytique`**.

Il corrige aussi trois erreurs de domaine relevées dans le schéma d'architecture proposé
(section 5).

Les sections de la spec du 2026-09-04 qui ne sont pas mentionnées ici restent valables :
retrait de NiFi, Airflow 3 comme ordonnanceur, MinIO, URL de sources épinglées, DAG
d'acquisition partagé et DAGs par panel, budget mémoire du VPS.

---

## 2. Décisions

### 2.1 Quatre couches

| Couche | Rôle en une phrase |
|---|---|
| `raw` | Copie fidèle de la source, pour rejouer sans rappeler l'API |
| `bronze` | Même contenu, rendu interrogeable en colonnes |
| `silver` | Données typées, filtrées, dédoublonnées, normalisées, historisées |
| `gold` | Données façonnées pour un consommateur précis (RAG ou analytique) |

La règle qui justifie une couche `raw` distincte du `bronze` : **le passage raw → bronze
change le format, et rien d'autre.** Sans cette règle, les deux couches feraient le même
travail.

C'est une variante assumée du médaillon classique, où le Bronze est lui-même la couche brute.
Elle correspond au modèle « zone d'atterrissage + Bronze ».

### 2.2 Polars comme moteur

Mesuré au cours de la conception, sur les transformations réelles du projet : Polars est
276 fois plus rapide que PySpark à 100 000 lignes et 22 fois à 5 millions, pour 1,9 fois
moins de mémoire. Le goulot du pipeline est le rate limit des API NCBI, pas le calcul.

Le bulk ClinVar non filtré compte environ 6 millions de lignes. Polars le traite en mode
**lazy** (`scan_csv` puis écriture en flux) ; il ne doit jamais être chargé entièrement en
mémoire sur le VPS de 12 Go.

### 2.3 Formats par couche

| Couche | Format | Chemin MinIO |
|---|---|---|
| `raw` | format d'origine (TSV gzippé, JSONL gzippé) | `raw/<source>/dt=AAAA-MM-JJ/[panel=<p>/]` |
| `bronze` | **Parquet** | `bronze/<source>/dt=AAAA-MM-JJ/[panel=<p>/]` |
| `silver` | **Delta Lake** | `silver/<entité>/` |
| `gold/rag` | **Delta Lake** | `gold/rag/<table>/` |
| `gold/analytique` | **Delta Lake** | `gold/analytique/<table>/` |

Quatre buckets MinIO : `raw`, `bronze`, `silver`, `gold`.

**Pourquoi Parquet en Bronze.** Le Bronze reflète des sources dont le projet ne contrôle pas
le schéma : les réponses de l'API NCBI ont des champs optionnels (le code gère déjà un
`conceptmeta` parfois absent chez MedGen). Delta impose son schéma et lève
`SchemaMismatchError` sur une écriture non conforme (mesuré) : en Bronze, le pipeline
échouerait le jour où NCBI ajoute un champ. Chaque mois est une partition écrite une fois et
jamais modifiée, lue ensuite par la seule tâche Silver ; Delta n'apporterait rien.

**Pourquoi Delta à partir du Silver.** ClinVar ne fait pas qu'ajouter des variants, il modifie
ceux qui existent. Mesuré entre les archives d'août et de septembre 2026, sur 44 495 variants
GRCh38 présents les deux mois :

| Changement en un mois | Variants | Part |
|---|---|---|
| Signification clinique | 39 | 0,1 % |
| Statut de revue | 33 | 0,1 % |
| Date de dernière évaluation | 162 | 0,4 % |

Parmi eux, un variant BRCA1 du panel (AlleleID 45948 : `Pathogenic` →
`Pathogenic/Likely pathogenic`). Cela impose trois capacités que Parquet seul n'offre pas :

1. **`MERGE`** pour historiser les reclassifications (SCD2) au lieu d'écraser le mois
   précédent ;
2. **ré-embedding incrémental** du RAG : `MERGE` sur `chunk_id = hash(contenu)`, pour ne
   recalculer que les documents modifiés ;
3. **écritures atomiques** : le journal de transactions de Delta ferme la fenêtre
   d'incohérence relevée en revue de la tâche 6 (un rejeu interrompu peut laisser un
   `_SUCCESS` ancien au-dessus de données nouvelles, faute de renommage atomique sur le
   stockage objet). En Silver et en Gold, l'application et le RAG lisent pendant que le
   pipeline écrit.

Capacités vérifiées avec `deltalake` (delta-rs), sans Spark ni PyArrow : écriture ACID,
`MERGE` sur MinIO sans verrou externe, time travel, `OPTIMIZE`, `VACUUM`, contraintes
`CHECK`. DuckDB lit les tables Delta (`delta_scan`) mais ne sait pas en écrire : c'est Polars
et `deltalake` qui écrivent.

**Réserve.** L'échantillon mesuré couvre les variants les plus anciens (début des archives).
Sur le panel (~48 000 variants GRCh38), la proportion donnerait de l'ordre de 50
reclassifications par mois. C'est une estimation, à confirmer sur le fichier complet.

---

## 3. Contrat de chaque couche

| Passage | Fait | Ne fait jamais |
|---|---|---|
| source → `raw` | dépôt tel quel, `manifest.json`, `_SUCCESS`, version de source épinglée | filtrer, typer, parser, dédoublonner |
| `raw` → `bronze` | conversion en Parquet, noms de colonnes normalisés, colonnes techniques (`_source_version`, `_logical_date`, `_ingested_at`) | appliquer une règle métier, retirer une ligne non vide |
| `bronze` → `silver` | typage, filtre panel, filtre GRCh38, dédoublonnage `#AlleleID`, éclatement des lignes multi-gènes, parsing du XML MedGen, normalisation HGVS via RefSeq, historique des reclassifications | calculer des agrégats |
| `silver` → `gold` | jointures, mise en forme propre à chaque consommateur, agrégats | nettoyer |

### 3.1 `raw`

Déjà implémenté par les tâches 1 à 7, sous le nom de couche `bronze`. Seul le nom change.

### 3.2 `bronze`

- Les colonnes sont lues **en chaînes de caractères** : le typage est une décision métier, qui
  revient au Silver.
- Les JSONL de l'API sont lus avec un schéma explicite ou en chaînes, car l'inférence de
  schéma de Polars peut perdre des colonnes quand les champs varient d'un enregistrement à
  l'autre.
- Le XML `conceptmeta` de MedGen reste une chaîne.
- Une ligne entièrement vide peut être retirée. Une ligne incomplète est conservée.

### 3.3 `silver`

Une table Delta par entité : `clinvar_variant`, `clinvar_variant_gene`, `ncbi_gene`,
`refseq_transcript`, `medgen_concept`, `medgen_mim`, `medgen_inheritance`,
`hpo_gene_phenotype`, `hpo_term`. Colonne de partition : `panel`. Une ligne par entité, aucun
agrégat.

### 3.4 `gold/rag`

- **Unité : le variant**, avec le contexte de son gène, de ses maladies et de ses phénotypes.
  Les questions posées au système portent sur un variant (« rs80357906 sur BRCA1 est-il
  pathogène ? »), pas sur un gène.
- Chaque document porte ses références de citation : accession ClinVar, version, date de
  collecte.
- `chunk_id` = hash déterministe du contenu.

### 3.5 `gold/analytique`

- Modèle en étoile : `fact_variant` et ses dimensions (gène, maladie, phénotype,
  signification clinique, temps).
- Agrégats utiles sur des données majoritairement catégorielles : nombre de variants par gène
  et par signification, répartition des statuts de revue, reclassifications par mois.
- Lu par DuckDB pour l'application.

`gold/rag` et `gold/analytique` lisent tous deux le Silver, jamais l'un l'autre.

---

## 4. Orchestration par Airflow et contrôles qualité

### 4.1 Rôle d'Airflow

Airflow 3 reste l'ordonnanceur du pipeline, comme décidé le 2026-09-04. Il **déclenche,
ordonne, surveille et rejoue** les tâches ; il ne transporte ni ne transforme aucune donnée.

Concrètement, pour chaque passage de couche :

| Qui | Fait quoi |
|---|---|
| **Airflow** | lance la tâche au bon moment, dans le bon ordre, avec la date de travail et le panel ; retente en cas d'échec transitoire ; bloque la suite si un contrôle échoue |
| **Code Python dans `src/`** | contient toute la logique : ingestion, conversion Polars, règles Silver, mise en forme Gold |
| **Polars** | exécute les calculs, **à l'intérieur du processus de la tâche** lancé par Airflow |
| **MinIO** | stocke les quatre couches |

**Date de travail.** Dans Airflow 3, seuls les runs planifiés ont une date logique : un
run déclenché par un Asset, ou lancé à la main sans `--logical-date`, n'a pas de `ds`. Le
DAG d'acquisition travaille sur sa date logique et l'inscrit dans l'événement d'Asset qu'il
publie ; les DAGs de panel relisent cette date dans l'événement (ou dans `--conf` pour un
run manuel). Toutes les partitions d'un même mois portent ainsi la même date `dt=`.

Aucune logique métier ne réside dans un DAG. C'est ce qui permet de tester chaque
transformation par `pytest` sans Airflow ni conteneur.

Ce qui change par rapport au 2026-09-04 : chaque DAG gagne les tâches `raw_to_bronze`,
`check_bronze`, `bronze_to_silver`, `silver_to_gold_rag` et `silver_to_gold_analytique`. Ce
qui ne change pas : Airflow 3 avec `LocalExecutor`, métadonnées dans PostgreSQL, trois
retries avec backoff, erreurs de configuration non retentées (`AirflowFailException`),
déclenchement des DAGs de panel par un Asset.

**Contrainte à vérifier au sous-projet B.** Avec `LocalExecutor`, les tâches s'exécutent dans
le conteneur du scheduler, limité à 2 Go. La conversion du bulk ClinVar complet (~6 millions
de lignes) doit tenir dans cette limite : elle se fait en mode lazy et en flux, jamais en
chargeant le fichier en mémoire. Mesure de référence : 5 millions de lignes filtrées en
mode eager ont occupé 928 Mo.

### 4.2 Contrôles qualité entre couches

Chaque passage est précédé d'une tâche de contrôle qui bloque la propagation en cas d'échec :
`check_raw`, `check_bronze`, `quality_check_silver`.

`check_raw` contrôle la **complétude et la non-vacuité** des partitions : liste non vide,
`_SUCCESS` présent, `record_count` du manifest strictement positif. Il ne regarde pas le
contenu. Les contrôles de contenu (colonnes attendues, gènes résolus) sont la responsabilité
de `check_bronze`, au sous-projet B.

Le Bronze ne filtre pas sur le panel : la conversion d'une source partagée (bulk ClinVar,
fichier plat HPO) est donc identique pour tous les panels. Elle s'exécute **une seule fois,
dans le DAG d'acquisition**, sans quoi les 442 Mo du bulk seraient convertis une fois par
panel. L'Asset qui déclenche les DAGs de panel est publié après `check_bronze`.

```
DAG d'acquisition (mensuel)
  download_clinvar_bulk + download_hpo_files → check_raw
    → raw_to_bronze (clinvar, hpo) → check_bronze → [Asset]

DAG de panel (déclenché par l'Asset)
  ingest_ncbi_gene + ingest_refseq + ingest_hpo_terms + ingest_medgen → check_raw
    → raw_to_bronze (sources du panel) → check_bronze
    → bronze_to_silver → quality_check_silver
    → silver_to_gold_rag + silver_to_gold_analytique
```

`ingest_medgen` continue de lire le bulk ClinVar en `raw`, en flux, pour extraire les CUI.

---

## 5. Corrections de domaine

Relevées dans le schéma d'architecture proposé et vérifiées sur l'archive ClinVar de
septembre 2026.

**5.1 Les variants bénins sont conservés.** Un filtre « suppression des variants bénins » en
Silver empêcherait le système de répondre « ce variant est bénin » : il répondrait qu'il ne
sait pas, ou inventerait une réponse, ce qui dégrade la métrique de fidélité (Faithfulness)
fixée dans la problématique. Les proportions analytiques seraient également faussées. La
signification clinique est un attribut, jamais un critère de filtre.

**5.2 Le dédoublonnage appartient au Silver.** Sur l'échantillon mesuré, 197 `#AlleleID` sur
198 apparaissent deux fois : une ligne GRCh37 et une ligne GRCh38. Un `drop_duplicates()` sur
toutes les colonnes ne retire rien, puisque les lignes diffèrent. Dédoublonner sur
`#AlleleID` oblige à choisir un assemblage : c'est une règle métier.

**5.3 Les identifiants ne sont jamais normalisés en casse.** La colonne `Name` contient des
expressions HGVS comme `NM_014855.3(AP5Z1):c.80_83delinsTGCTG…`. Les mettre en minuscules
produit une autre mutation. Les HGVS, les accessions et les symboles de gènes sont exclus de
toute normalisation de texte.

**5.4 `RS# (dbSNP)` est un entier.** La colonne contient `397704705`, ou `-1` quand
l'identifiant est absent — pas `rs397704705`. Le contrôle de format attendu est un entier ou
`-1` ; le préfixe `rs` s'ajoute en Silver si nécessaire.

---

## 6. Impact sur l'existant

### 6.1 Code livré (tâches 1 à 7)

Aucune logique ne change. Le renommage de la couche `bronze` en `raw` touche 54 occurrences
dans 15 fichiers : la constante de `config.py`, les appels `partition_uri(BRONZE, …)` des
quatre scripts d'ingestion, des docstrings, et des chemins attendus dans les tests. Les 107
tests doivent rester verts après le renommage.

`config.py` expose `RAW`, `BRONZE`, `SILVER`, `GOLD`.

**Piège du renommage.** La constante `BRONZE` continue d'exister, mais change de sens : elle
désigne désormais la couche Parquet. Un appel oublié `partition_uri(BRONZE, …)` dans un
script d'ingestion ne lèverait aucune erreur — il déposerait silencieusement des données
brutes dans le bucket `bronze`. Le renommage doit donc être vérifié par les tests : chaque
script d'ingestion a un test qui affirme un chemin commençant par `raw/`.

### 6.2 Plan d'implémentation en cours

Les tâches 8 à 12 du plan du 2026-09-04 contiennent 80 mentions de `bronze` et supposent trois
couches. Elles sont à réaligner avant d'être dépêchées :

- tâche 8 (MedGen, termes HPO) : écrit et lit en `raw` ;
- tâche 9 (stubs) : devient `raw_to_bronze`, `bronze_to_silver`, `silver_to_gold_rag`,
  `silver_to_gold_analytique` ;
- tâches 10 et 11 (DAGs) : chaîne de la section 4 ;
- tâche 12 (Docker) : quatre buckets créés au démarrage.

Une tâche de renommage s'insère avant la tâche 8.

---

## 7. Découpage en sous-projets

Implémenter les quatre couches dépasse un seul plan. Chaque sous-projet suit son propre cycle
spec → plan → implémentation :

| Sous-projet | Contenu | Spec |
|---|---|---|
| **A** | Renommage `bronze` → `raw`, puis fin du plan en cours réaligné (tâches 8 à 12) | ce document |
| **B** | `raw` → `bronze` en Polars (Parquet) | à écrire |
| **C** | `bronze` → `silver` en Polars et Delta (dont l'historique des reclassifications) | à écrire |
| **D** | `silver` → `gold/rag` et `gold/analytique` | à écrire |

Le sous-projet A laisse les transformations en stubs documentés, sur le contrat de la
section 3 : le pipeline complet est câblé et échoue explicitement là où les sous-projets B à D
prendront le relais.

---

## 8. Points ouverts

- **Base vectorielle.** Le mémoire annonce ChromaDB ; le schéma proposé cite Weaviate et
  Qdrant. Un seul outil doit être retenu et justifié, au moment du sous-projet D ou de l'étape
  RAG.
- **Outil analytique.** Tableau et Power BI ne font pas partie de la stack. DuckDB sur les
  tables Gold alimente l'application Streamlit annoncée dans le mémoire.
- **Taux de reclassification** à confirmer sur le fichier ClinVar complet.
- **Schéma explicite des JSONL** en Bronze, à définir au sous-projet B.
- ~~**Rejeu interrompu en `raw` et `bronze`.**~~ Résolu au sous-projet A : voir le protocole
  d'écriture d'une partition ci-dessous.

### Protocole d'écriture d'une partition (`raw`, puis `bronze`)

`raw` et `bronze` sont des fichiers simples sur stockage objet, sans renommage atomique. Une
partition s'écrit donc toujours dans cet ordre :

1. **begin** : `begin_partition` supprime le `_SUCCESS` éventuel d'un run précédent ;
2. **données** : dépôt des fichiers de la partition ;
3. **manifest** : `manifest.json` ;
4. **`_SUCCESS`** en dernier (`finalize_partition`).

Un rejeu interrompu à n'importe quelle étape laisse une partition sans `_SUCCESS`, que
`check_raw` ou `check_bronze` refuse : il ne peut plus y rester un `_SUCCESS` ancien au-dessus
de données à moitié réécrites. La conversion `raw_to_bronze` (sous-projet B) suit le même
protocole.
