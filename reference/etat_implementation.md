# Audit de l'état réel de l'implémentation

**Date :** 2 octobre 2026
**Branche :** `pipeline/ingest`
**Données de référence :** archive ClinVar de septembre 2026, partition `dt=2026-09-01`
**Objet :** décrire ce que le projet fait réellement, preuves à l'appui, pour la rédaction du
mémoire.

---

## Méthode

**Ce qui a été fait :**
- lecture de tout le code : `src/`, `scripts/`, `dags/`, `docker/`, `docker-compose.yml` ;
- exécution des deux suites de tests ;
- lecture de l'historique Airflow dans le volume `genomique_postgres-data`, par un conteneur
  PostgreSQL temporaire supprimé ensuite ;
- mesure du contenu réel du lac MinIO (volume `genomique_minio-data`), en lecture seule, en
  démarrant puis en arrêtant le conteneur `genomique-minio` existant.

**Ce qui n'a pas pu être consulté :**
- les journaux de tâches Airflow : le volume `airflow-logs` ne contient que ceux du
  dag-processor ;
- le code ou les sorties des expériences d'embedding citées dans la spec E1 ;
- toute exécution réseau réelle : aucune collecte n'a été relancée.

**Légende des statuts :**

| Symbole | Signification |
|---|---|
| ✅ | Implémenté et vérifié (le code et des éléments d'exécution confirment le fonctionnement) |
| 🟡 | Implémenté dans le code, mais non vérifié en exécution |
| 🟠 | Partiellement implémenté |
| ⏳ | Prévu, mais non implémenté |
| ❓ | Impossible à déterminer avec les éléments disponibles |

---

## 1. Résumé de l'état réel du projet

**Le pipeline de données est réel et a produit des données vérifiables.** MinIO contient
`raw → bronze → silver → gold` pour 18 gènes et l'archive ClinVar de septembre 2026 :
- 96 892 variants dans le Silver ;
- 96 910 documents RAG dans le Gold.

**Tout le volet IA est absent du code** : RAG, embeddings, base vectorielle, LLM, API et
interface. Il n'existe qu'à l'état de spec (E1, non versionnée) et d'images de référence dans
`RAG/`. PostgreSQL ne sert qu'à Airflow.

**Une nuance importante sur l'orchestration.** L'historique Airflow ne contient **aucune
exécution de bout en bout réussie des DAGs de panel** :
- Le seul run, celui du 18/09, s'arrête sur les tâches Gold, qui étaient encore des squelettes
  vides à cette date.
- Les tables Silver (réécrites) et Gold actuelles datent du **23/09, entre 11 h 43 et
  12 h 03**, sans run Airflow correspondant. Elles ont donc été produites par un appel direct
  des fonctions, en dehors d'Airflow.

---

## 2. Architecture technique effectivement implémentée

| Technologie | Version | Rôle réel | Preuve | Statut |
|---|---|---|---|---|
| Python | 3.12 (image Airflow) | Tout le code | `docker/airflow/Dockerfile` | ✅ |
| Polars | 1.44.1 | Moteur de transformation, en lecture paresseuse pour ClinVar | `raw_to_bronze.py`, `bronze_to_silver.py` | ✅ |
| delta-rs (`deltalake`) | 1.6.3 | Tables Delta Silver et Gold : MERGE, overwrite par partition `panel` | historiques Delta lus dans MinIO | ✅ |
| MinIO | image épinglée par empreinte | Lac objet, un bucket par couche | `docker/minio/create-buckets.sh` et contenu du volume | ✅ |
| Apache Airflow | 3.3.1, LocalExecutor | 3 DAGs, 3 pools (`ncbi`, `silver_write`, `gold_write`) | table `dag_run` | 🟠 voir §5 |
| PostgreSQL | 16-alpine | **Uniquement la base de métadonnées d'Airflow** | `docker-compose.yml`, service `postgres` | ✅ |
| boto3, requests | 1.41.5 / 2.34.2 | Accès S3 et HTTP | `storage.py`, `http_client.py` | ✅ |
| pytest, responses | 9.1.1 / 0.26.2 | Tests sans réseau | `requirements-dev.txt` | ✅ |

**Technologies absentes ou abandonnées :**
- **NiFi :** implémenté puis écarté, archivé dans `archive/nifi/`, avec la justification dans
  `reference/choix_contexte.md`.
- **Aucune trace dans le code de :** ChromaDB, pgvector, BioBERT, sentence-transformers,
  FastAPI (projet), Streamlit, Litestar, LLM, RAGAS ou DuckDB.
- **FastAPI 0.136.3** est bien installé dans le venv, mais c'est une dépendance interne
  d'Airflow 3, pas du code du projet.
- **DuckDB** est cité dans une docstring de `silver_to_gold_analytique.py` (« Lu par DuckDB pour
  l'application ») et dans le README, mais il n'est ni installé ni utilisé.

---

## 3. Schéma textuel du flux de données

```
                    ┌──────────── dag_acquisition_sources (cron 0 6 10 * *) ────────────┐
FTP NCBI ClinVar ───┤ ingest_clinvar  → raw/clinvar/dt=…/variant_summary.txt.gz (442 Mo) │
(archive mensuelle) │                                                                   │
GitHub HPO ─────────┤ ingest_hpo_files → raw/hpo/dt=…/genes_to_phenotype.txt (tag v…)    │
(release taguée)    │ check_raw_shared → raw_to_bronze_shared → check_bronze_shared ────┼─► Asset SOURCES_READY
                    └───────────────────────────────────────────────────────────────────┘
                                        │ (déclenche les 2 DAGs de panel : brca, sickle)
                    ┌───────────────────▼──── dag_genomic_pipeline_{brca|sickle} ─────────┐
E-utilities NCBI ───┤ ingest_ncbi_gene, ingest_refseq, ingest_medgen  (pool ncbi = 1 slot) │
ontology.jax.org ───┤ ingest_hpo_terms                                                    │
                    │ check_raw → raw_to_bronze → check_bronze                            │
                    │ bronze_to_silver (10 tables Delta, SCD2 sur clinvar_variant)        │
                    │ quality_check_silver                                                │
                    │ silver_to_gold_rag ─────► gold/rag/documents (Delta)                │
                    │ silver_to_gold_analytique ► gold/analytique/* (13 tables Delta)     │
                    │ quality_check_gold                                                  │
                    └─────────────────────────────────────────────────────────────────────┘
                                        │
                          [ RIEN au-delà : pas d'embeddings, pas d'index, pas de LLM, pas d'API ]
```

---

## 4. Sources de données et mécanismes de collecte

| Source | Mécanisme exact | Filtre / sélection | Volume réel au 18/09 (manifests) | Statut |
|---|---|---|---|---|
| **ClinVar** | `ingest_clinvar.py` → `archive_url_for()` : `…/tab_delimited/archive/variant_summary_{AAAA-MM}.txt.gz`, téléchargement en flux dans un fichier `.part` puis renommage atomique, contrôle `Content-Length` | Aucun en raw (bulk complet) ; filtre panel et GRCh38 en Silver | 442 495 433 octets ; bronze = **9 049 133 lignes** | ✅ |
| **HPO, fichier plat** | `ingest_hpo_files.py` : tag résolu par la redirection de `/releases/latest`, puis téléchargement de l'URL taguée | Aucun en raw | tag `v2026-09-01`, 20,8 Mo, bronze = 333 983 lignes | ✅ |
| **HPO, termes** | `ingest_hpo_terms.py` : `GET ontology.jax.org/api/hp/terms?filter=…`, par lots de 20 identifiants | Gènes du panel | brca 1 843, sickle 507 enregistrements | ✅ |
| **NCBI Gene** | `ncbi_gene.py` : esearch `{gene}[gene] AND human[organism] AND alive[property]`, puis esummary du **premier** UID | 18 symboles | brca 12, sickle 6 | ✅ |
| **RefSeq** | `refseq.py` : esearch nuccore `… srcdb_refseq[prop] AND biomol_mrna[prop]`, puis un esummary par UID | 18 gènes | 200 transcrits en Silver | ✅ |
| **MedGen** | `ingest_medgen.py` : CUI extraits de la colonne `PhenotypeIDS` du ClinVar brut (lecture en flux), puis esearch `{cui}[conceptid]` + esummary | CUI des variants du panel | brca 349, sickle 94 concepts | ✅ |

**Gestion des erreurs, telle que constatée dans le code :**

*Erreurs réseau*
- `build_retrying_session()` relance jusqu'à 3 fois sur les codes 429, 500, 502, 503 et 504,
  avec un délai croissant (`backoff_factor=1`) et le respect de l'en-tête `Retry-After`.
- Le limiteur de débit vise 0,34 s entre deux appels sans clé, 0,11 s avec clé
  (`RateLimiter`).
- Dans les messages d'erreur, la clé API NCBI est masquée (`NcbiRequestError`).
- Les appels à l'API HPO **ne passent pas par le limiteur** : seule la session avec relances
  les protège.

*Réponses vides*
- Un gène ou un CUI non résolu garde son enregistrement, avec un contenu vide.
- Le verdict est reporté au contrôle de partition et aux contrôles Silver.

*Doublons*
- CUI : dédoublonnés à l'extraction.
- Identifiants HPO : dédoublonnés avant l'appel à l'API.
- Variants : dédoublonnés par `alleleid` en Silver.

*Panel limité*
- La collecte couvre 18 gènes et deux panels, pas ClinVar entier : `config.py`, `ALL_GENES`.

*Vérifications d'intégrité absentes*
- Aucune vérification de la somme MD5 publiée par ClinVar (TODO C2).
- Aucune vérification du schéma des sources à l'entrée (TODO P13).

**Le collecteur historique `scripts/run_collection.py` n'a laissé aucune trace
d'exécution** : `data/raw/` est vide. Statut 🟡.

---

## 5. Pipeline de traitement en détail

### 5.1 Raw (format de la source) ✅

Chaque partition suit le protocole `begin_partition` (suppression de l'ancien `_SUCCESS`),
puis écriture des données, puis `manifest.json`, puis `_SUCCESS` (`storage.py`).

Le manifest porte :
- la source et son URL ;
- `source_version`, la version épinglée de la source : mois d'archive ClinVar ou tag HPO ;
- `record_count` ;
- `written_at`.

### 5.2 Bronze (Parquet) ✅ — `raw_to_bronze.py`

- **Ce que fait la conversion :**
  - colonnes lues en chaînes ;
  - noms de colonnes normalisés mécaniquement (`#AlleleID` → `alleleid`) ;
  - lignes entièrement vides retirées ;
  - ajout de trois colonnes techniques : `_source_version`, `_logical_date`, `_ingested_at`.
- Les champs imbriqués JSON restent des chaînes JSON, sans aplatissement.
- **Ce qu'elle ne fait pas :** aucun filtre, aucun typage, aucun dédoublonnage.

### 5.3 Silver (Delta, 10 tables) ✅ — `bronze_to_silver.py`

**Volumes réels :**

| Table | Lignes |
|---|---|
| `clinvar_variant` | 96 892 (brca 93 381 / sickle 3 511) |
| `clinvar_variant_gene` | 96 892 |
| `clinvar_variant_disease` | 170 475 |
| `ncbi_gene` | 18 |
| `refseq_transcript` | 200 |
| `medgen_concept` | 443 |
| `medgen_mim` | 227 |
| `medgen_inheritance` | 133 |
| `hpo_gene_phenotype` | 2 350 |
| `hpo_term` | 2 350 |

**Transformations réelles :**
- Filtre `assembly == "GRCh38"`.
- Éclatement de `genesymbol` sur `;`, pour ne pas perdre les variants rattachés à plusieurs
  gènes.
- Dédoublonnage par `alleleid`, en gardant la première ligne.
- `rs_dbsnp` converti en entier.
- Éclatement aligné de `phenotypelist` et `phenotypeids`, avec suppression de « not provided »
  et « not specified ».
- Extraction des identifiants MedGen, OMIM, Orphanet et MONDO.

**Ce que le code appelle « HGVS » — ne pas l'appeler « normalisation HGVS » :**
- Une expression régulière (`_HGVS_PATTERN`) découpe le champ `Name` de ClinVar en quatre
  parties : accession, version, `hgvs_c`, `hgvs_p`.
- Puis on vérifie seulement que l'**accession**, sans sa version, figure dans le catalogue
  RefSeq collecté (`refseq_accession_known`).
- Il n'y a ni validation syntaxique ou sémantique HGVS (bibliothèque `hgvs`,
  VariantValidator…), ni conversion de coordonnées.
- Résultat réel : 5 045 variants (5,2 %) ont `refseq_accession_known = False`, et 808 n'ont
  pas de `hgvs_c`.
- Formulation juste : « **extraction et contrôle de cohérence des descripteurs HGVS fournis
  par ClinVar** ».

**Historique SCD2 sur `clinvar_variant`**
- Ce qui déclenche une nouvelle version : un changement de `clinicalsignificance`,
  `reviewstatus` ou `lastevaluated`.
- Le mécanisme est testé, mais **jamais exercé sur deux mois réels** :
  - un seul mois a été ingéré ;
  - les 96 892 lignes sont toutes `is_current` ;
  - `fact_reclassification` contient 0 ligne.
- Limite documentée : un variant retiré par ClinVar n'est jamais clôturé.
  `quality_check_silver` compense par un seuil d'alerte de 5 %.

**`quality_check_silver`** vérifie :
- que les 10 tables sont non vides (sauf `hpo_gene_phenotype`) ;
- qu'il n'y a aucun gène hors panel ;
- qu'un variant n'a qu'une seule ligne courante ;
- qu'il n'y a pas d'`alleleid` sans correspondance entre les tables ;
- qu'au plus 5 % des variants courants ont disparu d'un mois sur l'autre.

Ce sont des **contrôles d'intégrité et de cohérence**, pas une validation biologique.

### 5.4 Gold ✅ pour les données, 🟠 pour l'orchestration

**`gold/rag/documents`** — 96 910 lignes (96 892 variants + 18 gènes) :
- un texte anglais généré par gabarit (`render_variant_document`, `render_gene_document`) ;
- maladies plafonnées à 5 et phénotypes à 10 ;
- `doc_id` stable ;
- `chunk_id` = SHA-256 du texte ;
- écriture par MERGE incrémental.

Mesures réelles :
- longueur : min 149, médiane 607, max 1 467 caractères ;
- `doc_id` et `chunk_id` 100 % uniques ;
- 4 645 documents de variant sans maladie associée ;
- 31 802 documents sans phénotype.

**`gold/analytique`** — 13 tables en étoile :

| Table | Lignes |
|---|---|
| `fact_variant` | 96 892 |
| `fact_variant_disease` | 170 475 |
| `fact_reclassification` | **0** |
| `dim_gene` | 18 |
| `dim_disease` | 442 |
| `dim_phenotype` | 968 |
| `bridge_gene_phenotype` | 2 350 |
| `dim_clinical_significance` | 36 |
| `dim_review_status` | 17 |
| `dim_month` | 2 |
| `agg_variants_by_gene_significance` | 177 |
| `agg_review_status` | 105 |
| `agg_reclassifications_by_month` | 0 |

Aucun consommateur n'existe pour ces tables.

**`quality_check_gold`** vérifie :
- la conservation des variants ;
- un document par variant et par gène ;
- l'unicité des identifiants ;
- un texte d'au plus 2 000 caractères ;
- l'absence de clé pendante vers `dim_gene` et `dim_disease`.

**Il n'a jamais tourné dans Airflow.** Je n'ai pas pu déterminer s'il a été lancé à la main sur
le lac réel (❓).

### 5.5 Orchestration — ce que montre la base Airflow

| Run | État | Détail |
|---|---|---|
| `dag_acquisition_sources` 18/09 | ✅ success, 1 min 08 s | `raw_to_bronze_shared` : 30 s pour 9 M de lignes. Le téléchargement ClinVar n'a pris que 7,8 s car le fichier était **déjà en cache** : ce n'est pas un temps de téléchargement. |
| `dag_genomic_pipeline_brca` 18/09 | ❌ failed | Tout est vert jusqu'à `quality_check_silver`. `silver_to_gold_*` échoue 4 fois : à cette date (commit `2770322`), ces fonctions étaient des squelettes vides. `ingest_medgen` : **470 s**. |
| `dag_genomic_pipeline_sickle` 18/09 | ❌ failed | Même cause. `ingest_medgen` : 394 s. |
| Ancienne stack (`rag_genomique_*`) 15/09 | ❌ failed / running | — |

**Historique Delta des tables (dates d'écriture) :**
- `silver/clinvar_variant` : version 0 (WRITE) le 18/09 à 14 h 08, version 1 (MERGE) le 18/09
  à 14 h 15, puis aucune nouvelle version lors du rejeu du 23/09 ;
- autres tables Silver : réécrites le 23/09 entre 11 h 43 et 11 h 44 ;
- `gold/rag/documents` : version 0 le 23/09 à 12 h 03 min 36 s, version 1 (MERGE) à
  12 h 03 min 42 s ;
- `gold/analytique/*` : écrites le 23/09 à 12 h 03.

**Mécanismes de reprise en place :**
- relances (3 tentatives toutes les 5 minutes) ;
- `AirflowFailException` pour les erreurs de configuration, qui ne sont pas relancées ;
- partitions idempotentes et marqueurs `_SUCCESS` ;
- pools à un seul slot ;
- alertes e-mail codées, mais **SMTP non branché** (TODO §1).

**Reproductibilité** : bonne par construction. Le mois d'archive ClinVar et le tag HPO sont
épinglés et inscrits dans les manifests.
- Pour NCBI Gene, RefSeq et MedGen, `source_version` vaut la date du run : ces API ne sont
  **pas versionnées**, donc un rejeu ultérieur peut donner des résultats différents.
- Côté Silver, le MERGE n'a créé aucune version Delta lors du rejeu du 23/09, ce qui confirme
  l'idempotence de `clinvar_variant`.

---

## 6. Stockage relationnel et vectoriel

- **PostgreSQL** : une seule base, `airflow`, pour les métadonnées d'Airflow. Aucun schéma
  métier, aucune table de variants, aucune contrainte métier. ✅
- **pgvector** : ⏳ prévu seulement.
  - La spec E1, datée du 01/10, prévoit `pgvector/pgvector:0.8.6-pg16` dans un service dédié,
    trois comptes et `RAG/sql/001_schema.sql`.
  - Rien de tout cela n'existe : pas de service dans `docker-compose.yml`, pas de SQL, aucun
    vecteur, aucun index.
- **Le stockage « relationnel » réel est le lac Delta** : 10 tables Silver et 14 tables Gold.
  - Il n'impose aucune clé primaire ni clé étrangère.
  - L'intégrité est vérifiée *a posteriori* par `quality_check_silver` et
    `quality_check_gold`.

---

## 7. Embeddings, recherche et système RAG

| Élément | Statut | Constat |
|---|---|---|
| Préparation du texte à vectoriser | ✅ | `gold/rag/documents`. Unité = un variant ou un gène, sans découpage. |
| Métadonnées de filtrage | ✅ | Couverture mesurée : `gene_symbol` 100 %, `clinical_significance` 100 %, `hgvs_c` 99,2 %, rs 85,5 % (14 034 valeurs à `-1`). |
| Modèle d'embedding | ⏳ | Non choisi. La spec E1 compare BioBERT (`dmis-lab/biobert-base-cased-v1.2`) et `NeuML/pubmedbert-base-embeddings` (768 dimensions). |
| Vectorisation, index, métrique | ⏳ | Aucun code. |
| Recherche hybride et filtrage | ⏳ | Prévue pour E2. |
| Prompt, LLM, citations | ⏳ | « LLM Anthropic » cité dans la spec, aucun code. Le champ `clinvar_url` du Gold permettra des citations. |
| Garde-fous anti-hallucination | ⏳ | Aucun. |
| Évaluation RAGAS | ⏳ | Aucune mesure. |

**Mesures citées dans la spec E1 :**
- débits : 7,0 doc/s sur CPU avec ONNX, 242 doc/s sur GPU ;
- cosinus moyen avec le plus proche voisin : 0,988 ;
- 257 tokens au maximum.

Ces chiffres sont ❓ : **aucun script ni aucune sortie ne les accompagne dans le dépôt**, et
`docs/` est exclu de git (`.gitignore`, ligne 12).

---

## 8. API et interface

**Aucune API ni interface n'est implémentée** (⏳).
- Aucun endpoint, aucune application Streamlit, aucun code dans `RAG/` (qui ne contient que
  `consigne.md` et `architecture RAG.jpeg`).
- Les seules interfaces existantes sont celles de l'infrastructure :
  - l'interface Airflow sur `127.0.0.1:8080` ;
  - la console MinIO sur `127.0.0.1:9011`, d'après le `.env`.

---

## 9. Tests et résultats vérifiables

**Exécution des deux suites le 02/10/2026 :**
- `pytest -q` : **284 passed, 1 deselected, en 19,3 s**. Le test exclu est un test
  d'intégration MinIO (`@pytest.mark.integration`).
- `pytest tests_airflow -q` : **24 passed**, en 7,2 s.

**Répartition des 283 fonctions de test** (les 284 tests comptent les cas paramétrés) :

| Dossier | Fonctions de test |
|---|---|
| `tests/ingestion` | 123 |
| `tests/transformations` | 117 |
| `tests/scripts` | 29 |
| `tests/orchestration` | 10 |

Ce sont des tests unitaires, avec des fixtures et du HTTP simulé (`responses`). Il n'existe
**aucun test d'intégration exécuté automatiquement**, ni aucun test du comportement en panne
contre la vraie stack.

**Mesures déjà disponibles et vérifiables** :
- les volumes par couche (§4 et §5) ;
- les durées des tâches, lisibles dans la table `task_instance` ;
- les historiques Delta ;
- les tailles de fichiers.

**Indicateurs calculables tout de suite à partir du lac :**
- taux de résolution HGVS (94,8 % d'accessions connues) ;
- taux de variants sans maladie ;
- répartition par signification clinique et par statut de revue ;
- taux de dédoublonnage (9 049 133 lignes en bronze, puis filtre panel et GRCh38, puis
  96 892 variants) ;
- rapport de compression entre raw et bronze.

**Expériences encore nécessaires :**
1. Un run Airflow complet et réussi des trois DAGs, avec captures d'écran.
2. Un second mois ClinVar, pour exercer le SCD2 et `fact_reclassification`.
3. Les tests de panne et de restauration, niveaux 5 et 6 de `evaluation.md`.
4. La confrontation de l'échantillon de onze variants aux fiches ClinVar (niveau 7).
5. Plus tard : la comparaison des modèles d'embedding et RAGAS.

---

## 10. Fonctionnalités terminées, partielles et restantes

| Terminé et vérifié ✅ | Partiel 🟠 / non vérifié 🟡 | Restant ⏳ |
|---|---|---|
| Collecte des 5 sources (6 connecteurs) vers raw | DAGs de panel : jamais exécutés en entier avec succès 🟠 | Base vectorielle pgvector |
| raw → bronze → silver → gold, données réelles en MinIO | `quality_check_gold` sur données réelles ❓ | Embeddings, choix du modèle |
| Contrôles de partition et contrôles Silver dans Airflow | SCD2 sur des données mensuelles réelles 🟡 | Recherche hybride |
| Idempotence du rejeu Silver | Alertes e-mail (code présent, SMTP absent) 🟠 | Prompt, LLM, citations |
| Stack Docker durcie | Collecteur historique `run_collection.py` 🟡 | API, interface |
| 308 tests verts | Sauvegarde (`sauvegarde.sh` écrit, cron non installé, restauration non testée) 🟠 | RAGAS, tests de panne et de restauration, validation métier |

---

## 11. Problèmes, limites et incohérences à corriger

1. **« Exécution de bout en bout ✅ » dans `reference/evaluation.md` n'est pas confirmée par
   Airflow.** Le Gold a été produit hors orchestrateur le 23/09.
2. **Contradictions entre documents** :
   - base vectorielle : `Problematique_Projet_RAG_Genomique.md` annonce ChromaDB, la spec E1
     annonce pgvector ;
   - API : la problématique annonce FastAPI et Streamlit, la spec E1 annonce Litestar ;
   - modèle : `TODO.md` parle d'« embeddings BioBERT », alors que la spec prévoit un choix par
     mesure ;
   - sources : la problématique cite GenBank, dbSNP et ClinVar *via Entrez*. En réalité,
     ClinVar est lu par FTP, et ni GenBank ni dbSNP ne sont interrogés (on ne garde que
     l'identifiant rs).
3. **`docs/` est exclu de git** : les specs et plans qui justifient les choix ne sont pas
   versionnés.
4. **DuckDB** est annoncé comme lecteur du Gold analytique, mais il n'est ni installé ni
   utilisé.
5. **Docstrings périmées** : « neuf tables » dans `bronze_to_silver` et `quality_check_silver`,
   alors que `SILVER_TABLES` en compte dix.
6. **Le fichier de consignes internes (non versionné) contient deux affirmations fausses** :
   - « tests en moins de 3 s » : j'ai mesuré 19 s ;
   - « diagramme Mermaid non commité » : il l'a été dans `0433cab`.
7. **Divergence de filtre d'assemblage** : le collecteur historique garde
   `Assembly ∈ {GRCh38, na}`, le Silver garde seulement `GRCh38`.
8. **`refseq_accession_known` ignore la version du transcrit**, qui est pourtant extraite.
9. **MedGen domine la durée d'un panel** (de 6 à 8 minutes), parce qu'il fait un appel
   esummary par CUI sans regroupement.
10. **Listes de phénotypes polluées** par des modes de transmission et des âges d'apparition.
    C'est connu, et volontairement non corrigé avant la première mesure RAGAS.

---

## 12. Questions ouvertes

1. **Comment le Silver et le Gold du 23/09 ont-ils été produits ?** Par
   `docker exec … python -c`, ou par un autre moyen ? `quality_check_gold` a-t-il été lancé, et
   la sortie en a-t-elle été gardée ?
2. **Un run complet des DAGs de panel a-t-il réussi** sur une autre machine ou une stack
   supprimée depuis ? Sinon, en faire un avant la rédaction.
3. **Où se trouvent le code et les sorties des mesures d'embedding** de la spec E1 (débits,
   cosinus 0,988) ?
4. **Quelle version fait foi pour le mémoire** : ChromaDB ou pgvector, FastAPI et Streamlit ou
   Litestar, et quel LLM ?
5. L'exclusion de `docs/` de git est-elle volontaire ?
6. La vérification manuelle des onze variants de `evaluation.md` §8 a-t-elle été faite ?

---

## Informations exploitables pour la rédaction du mémoire

### Ce que l'on peut déjà présenter
- **L'architecture médaillon** : MinIO, Parquet puis Delta, Polars, et le protocole de
  partition (`_SUCCESS` et manifest).
- **La collecte** : 5 sources par 6 connecteurs, avec leurs mécanismes exacts (FTP épinglé
  par mois, release HPO taguée, E-utilities avec limiteur de débit et relances).
- **Les volumes réels de septembre 2026** :
  - 9 049 133 lignes ClinVar en bronze ;
  - 96 892 variants dans le Silver ;
  - 170 475 associations variant-maladie ;
  - 96 910 documents RAG.
- **La modélisation** :
  - 10 tables Silver ;
  - un modèle en étoile de 13 tables ;
  - les documents RAG avec un `chunk_id` qui sert au ré-embedding incrémental.
- **Les contrôles qualité** par couche, décrits comme des contrôles d'intégrité.
- **La sécurité de la stack** : images épinglées, compte MinIO au moindre privilège, ports
  liés à la boucle locale.
- **Le choix d'Airflow contre NiFi**, avec mesures.
- **308 tests automatisés.**

### Ce qui demande des preuves supplémentaires
- **L'orchestration de bout en bout par Airflow** : il faut un run réussi.
- **`quality_check_gold` sur les données réelles.**
- **Les mesures de la spec E1** : débits, équivalence GPU/CPU, proximité des documents.
- **L'idempotence du Gold** : elle est affirmée « vérifiée à la main », mais sans trace.

### Ce qu'il reste à mesurer
- La durée d'un cycle complet, téléchargement réel compris.
- Le pic mémoire.
- Un second mois, pour le SCD2.
- Les tests de panne et de restauration.
- La justesse métier sur un échantillon.
- Ensuite, le choix du modèle d'embedding et les quatre métriques RAGAS.

### Ce qu'il ne faut pas écrire en l'état
- « Le système RAG est implémenté », ou toute affirmation sur les embeddings, la recherche
  vectorielle, le LLM, l'API ou l'interface.
- « Les données sont stockées dans PostgreSQL/pgvector » ou « dans ChromaDB ».
- « Normalisation HGVS » ou « validation biologique ».
- « Le pipeline est orchestré de bout en bout par Airflow avec succès ».
- « Les reclassifications ClinVar sont suivies dans le temps ». Le mécanisme existe, mais il
  n'y a aucune donnée.
- « Les données sont collectées depuis dbSNP et GenBank ».
- Les valeurs cibles RAGAS de la problématique présentées comme des résultats.
