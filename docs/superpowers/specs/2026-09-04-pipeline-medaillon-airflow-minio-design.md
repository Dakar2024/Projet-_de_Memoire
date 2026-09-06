# Pipeline médaillon Bronze/Silver/Gold — Airflow + MinIO — Design

**Date :** 2026-09-04
**Étape :** 2 du projet (la collecte RAW est l'étape 1, déjà livrée)
**Statut :** validé, prêt pour le plan d'implémentation

---

## 1. Contexte et périmètre

L'étape 1 a produit une couche de collecte fonctionnelle : quatre modules d'ingestion
(`src/ingestion/`), 63 tests unitaires passant en 1,7 s sans réseau ni infrastructure, et un
script d'orchestration `scripts/run_collection.py` produisant un JSON par gène dans
`data/raw/`.

Cette étape 2 remplace ce point de sortie par une **architecture médaillon sur stockage
objet**, ordonnancée par Airflow. Elle ne réécrit pas la logique de collecte.

### Ce qui est dans le périmètre

- Décomposition de la collecte en cinq tâches d'ingestion indépendantes écrivant en Bronze.
- Ajout d'une cinquième source : le catalogue des transcrits RefSeq (`db=nuccore`).
- Infrastructure Docker Compose : Airflow 3, PostgreSQL, MinIO.
- Les DAGs, leurs dépendances, leurs contrôles qualité et leur idempotence.
- Les contrats des trois couches et le plan de stockage MinIO.

### Ce qui n'est pas dans le périmètre

- **Le moteur de transformation Silver/Gold n'est pas arbitré.** Les tâches
  `bronze_to_silver` et `silver_to_gold` sont livrées en stubs explicites.
- Le durcissement des scripts d'ingestion à grande échelle (pagination, reprise sur erreur,
  batching des appels) est reporté à une étape ultérieure, décision prise sciemment.
- Le RAG (chunking, embeddings, vector store, LLM) et l'application web.

---

## 2. Décisions d'architecture

### 2.1 NiFi est retiré

NiFi apportait le déclenchement planifié, le routage succès/échec et la journalisation —
un **sous-ensemble strict** de ce qu'Airflow fournit, pour un coût mesuré de **1,37 Gio de RAM
au repos avec un flow vide** (image de 2,25 Go, démarrage en 61,6 s).

Le profil des sources ne justifie pas un outil de dataflow : deux fichiers plats publiés
mensuellement et des appels REST séquentiels. Aucun flux continu, aucune backpressure,
aucun routage à haut débit.

NiFi reste dans le dépôt et sera documenté dans le mémoire comme **alternative implémentée,
mesurée et écartée** — une justification instrumentée vaut mieux qu'un outil de plus.

### 2.2 Airflow 3 est ordonnanceur, jamais moteur

Airflow déclenche, ordonne, surveille et rejoue. Il ne transporte ni ne transforme aucune
donnée. Aucune logique métier ne réside dans un DAG : les tâches appellent des fonctions de
`src/`, testables par `pytest` sans qu'Airflow soit installé.

Airflow 3 est retenu pour ses **Assets** : la planification pilotée par la donnée relie le
DAG d'acquisition aux DAGs de panel sans couplage temporel, et produit un graphe de lineage
généré plutôt que dessiné.

Conséquence sur les noms de services : en Airflow 3 le `webserver` est remplacé par
`api-server`, et le `dag-processor` est un service distinct.

### 2.3 Le format de stockage n'est pas le moteur de calcul

Silver et Gold sont des **tables Delta Lake**. Ce choix ne présuppose aucun moteur : Delta
est écrit indifféremment par Spark, delta-rs, Flink ou Trino. Fixer le format maintenant
préserve donc entièrement l'arbitrage du moteur, tout en donnant dès aujourd'hui l'ACID, le
time-travel et le `MERGE`.

Capacités vérifiées sur MinIO au cours de la conception : écriture ACID, `MERGE` (sans
verrou externe ni `AWS_S3_ALLOW_UNSAFE_RENAME`), time-travel, schema enforcement,
`OPTIMIZE`, `Z-ORDER`, `VACUUM`, contraintes `CHECK`, historique auditable.

### 2.4 Les scripts d'ingestion sont conservés

Aucune fonction de `src/ingestion/` n'est réécrite. Les modules deviennent des unités
d'exécution appelées par Airflow via de minces wrappers en ligne de commande. Seules trois
choses changent, et aucune ne touche à la logique métier :

1. les chemins de sortie deviennent paramétrables (`LAKE_URI`, `--logical-date`, `--genes`) ;
2. les URL de source sont épinglées sur une version ;
3. le téléchargement vérifie l'intégrité de ce qu'il a reçu.

---

## 3. Stockage MinIO

Trois buckets, un par couche. Le flux est **strictement unidirectionnel** :
source → bronze → silver → gold. Aucune couche n'écrit dans une couche inférieure.

### 3.1 Bronze — le format de la source, sans transformation

```
bronze/clinvar/dt=YYYY-MM-DD/          variant_summary.txt.gz     (TSV gzippé, 442 Mo, NON filtré)
bronze/hpo/dt=YYYY-MM-DD/              genes_to_phenotype.txt.gz  (partagé entre panels)
bronze/hpo_terms/dt=YYYY-MM-DD/panel=<panel>/   hpo_terms.jsonl.gz
bronze/ncbi_gene/dt=YYYY-MM-DD/panel=<panel>/   gene_summaries.jsonl.gz
bronze/refseq/dt=YYYY-MM-DD/panel=<panel>/      transcripts.jsonl.gz
bronze/medgen/dt=YYYY-MM-DD/panel=<panel>/      concepts.jsonl.gz
```

Chaque partition est close par deux objets :

- `_SUCCESS` — marqueur de complétude ;
- `manifest.json` — nombre d'enregistrements, URL source, **version de source épinglée**,
  taille attendue et taille reçue, horodatage, `logical_date`.

Le format JSONL est retenu pour les réponses d'API : il préserve la réponse mot pour mot,
reste lisible ligne à ligne, et n'impose aucun schéma — donc aucune transformation. Le XML
`conceptmeta` de MedGen est conservé tel quel, en chaîne de caractères.

Le bulk ClinVar est déposé **non filtré**. Le filtrage sur le panel est une transformation :
il appartient à Silver. Cette décision maintient Bronze strictement brut et retire toute
dépendance à un moteur de calcul de la couche d'ingestion.

### 3.2 Silver — une table Delta par entité

```
silver/clinvar_variant/            silver/clinvar_variant_gene/
silver/ncbi_gene/                  silver/refseq_transcript/
silver/medgen_concept/             silver/medgen_mim/            silver/medgen_inheritance/
silver/hpo_gene_phenotype/         silver/hpo_term/
```

Chaque table Delta est un préfixe MinIO contenant du Parquet compressé en ZSTD et un
`_delta_log/` portant les transactions. Colonne de partition : `panel`.

Traitements attendus à ce niveau (spécifiés ici, implémentés quand le moteur sera arbitré) :

- filtrage du bulk sur le panel ;
- éclatement des lignes ClinVar multi-gènes (`GeneSymbol` joint par `;`) en table de liaison
  `clinvar_variant_gene` — récupère les ~0,3 % d'associations aujourd'hui perdues ;
- aplatissement du XML `conceptmeta` en tables normalisées ;
- éclatement de `PhenotypeIDS` ;
- normalisation HGVS, adossée au catalogue `refseq_transcript` ;
- typage, déduplication, harmonisation des identifiants ;
- historisation SCD2 de la signification clinique, pour tracer les reclassifications de
  variants (VUS → pathogène), qui sont un phénomène réel et cliniquement significatif.

### 3.3 Gold — façonnée par son consommateur, le RAG

```
gold/variant_enriched/     variant × gène × phénotype HPO × signification clinique
gold/rag_document/         texte en langue naturelle pré-rendu + charge de citation
gold/rag_chunk/            chunks, identifiant = hash de contenu
```

L'identifiant de chunk est un **hash déterministe du contenu**. Combiné au `MERGE` de Delta,
il permet de ne ré-embedder que ce qui a changé d'un run mensuel à l'autre, au lieu de
recalculer l'intégralité du corpus.

`gold/` est la **seule couche que le RAG lit**.

### 3.4 Volumétrie estimée

| Couche | Par run mensuel | Sur un an |
|---|---|---|
| Bronze ClinVar | 442 Mo | ~5,3 Go |
| Bronze autres sources | ~5 Mo | ~60 Mo |
| Silver | ~30 Mo | ~360 Mo |
| Gold | ~40 Mo | ~480 Mo |
| **Total** | | **~6,2 Go/an** |

---

## 4. Idempotence

Un run est identifié par sa **date logique** `{{ ds }}`. Rejouer un run réécrit la partition
`dt=…` concernée, et rien d'autre. Aucune tâche n'a d'effet de bord non paramétré par `ds`.

Deux mécanismes le garantissent :

**Les URL de source sont épinglées sur une version, pas sur « latest ».** ClinVar publie des
archives mensuelles immuables (`variant_summary_2026-09.txt.gz`, vérifié HTTP 200) et HPO des
releases taguées (`releases/download/v2026-09-01/`). Les scripts actuels utilisent les URL
« latest », qui changent sous les pieds : rejouer `dt=2026-08-01` téléchargerait le fichier de
septembre. L'épinglage supprime ce défaut.

**La provenance porte `ds`, pas l'horloge murale.** Le champ `collected_at` actuel utilise
`datetime.now()`, ce qui rend deux exécutions du même `ds` non identiques.

---

## 5. Arborescence du dépôt

```
├── dags/
│   ├── dag_acquisition_sources.py        # sources partagées entre panels
│   ├── dag_genomic_pipeline_brca.py      # panel cancer du sein (12 gènes)
│   ├── dag_genomic_pipeline_sickle.py    # panel drépanocytose (6 gènes)
│   └── common/
│       ├── panels.py                     # mapping panel → gènes
│       └── tasks.py                      # fabriques de tâches partagées
├── src/
│   ├── ingestion/                        # logique métier inchangée
│   │   ├── config.py                     # + LAKE_URI, résolution file:// ou s3://
│   │   ├── storage.py        (nouveau)   # écriture atomique, _SUCCESS, manifest
│   │   ├── refseq.py         (nouveau)   # db=nuccore
│   │   ├── clinvar.py  ncbi_gene.py  medgen.py  hpo.py
│   │   ├── download.py  http_client.py
│   │   └── orchestrate.py                # plus appelé en Bronze
│   └── transformations/      (stubs)
│       ├── bronze_to_silver.py
│       └── silver_to_gold.py
├── scripts/
│   ├── ingest_clinvar.py       ingest_hpo_files.py    # DAG d'acquisition (partagé)
│   ├── ingest_ncbi_gene.py     ingest_refseq.py
│   ├── ingest_medgen.py        ingest_hpo_terms.py    # DAGs de panel
│   └── run_collection.py                 # conservé, chemin autonome hors Airflow
├── docker/
│   ├── airflow/Dockerfile
│   └── minio/create-buckets.sh
├── config/panels.yml
├── tests/
├── docker-compose.yml
└── requirements.txt  requirements-dev.txt
```

---

## 6. Les DAGs

### 6.1 `dag_acquisition_sources` — mensuel, indépendant des panels

```
download_clinvar_bulk ─┐
                       ├─► check_bronze_shared ─► [Asset : sources_pretes]
download_hpo_files ────┘
```

`download_hpo_files` ne fait que déposer `genes_to_phenotype.txt.gz` : l'enrichissement des
termes HPO (definition, synonymes, xrefs) dépend des gènes du panel et relève donc du DAG de
panel, où il est assuré par `ingest_hpo_terms`.

Les deux fichiers plats sont communs à tous les panels. Un DAG amont partagé évite de
télécharger 442 Mo une fois par panel. Il publie un Asset Airflow qui déclenche les DAGs de
panel — couplage par la donnée, pas par l'horaire.

### 6.2 `dag_genomic_pipeline_<panel>` — déclenché par l'Asset

```
ingest_ncbi_gene ─┐
ingest_refseq ────┤
ingest_hpo_terms ─┼─► check_bronze ─► bronze_to_silver ─► quality_check_silver
ingest_medgen ────┘                        (stub)              │
      ▲                                                        ▼
      └── lit bronze/clinvar                          silver_to_gold ─► publish_gold
          (les CUI viennent de PhenotypeIDS)              (stub)
```

**`ingest_medgen` a une dépendance de données sur ClinVar** : les CUI MedGen sont extraits du
champ `PhenotypeIDS` des lignes ClinVar. Il lit donc la partition Bronze ClinVar pour piloter
ses appels d'API, mais ne persiste aucune transformation — le flux reste unidirectionnel.

### 6.3 Paramètres et communication

Airflow passe aux scripts la date logique `{{ ds }}`, la liste de gènes du panel et l'URI de
destination. **Rien d'autre ne transite par XCom que des métadonnées légères** : chemin du
manifest et nombre d'enregistrements.

### 6.4 Contrôles qualité

Chaque passage de couche est précédé d'une tâche de vérification : présence du `_SUCCESS`,
cohérence du manifest, nombre de lignes non nul, colonnes attendues, gènes du panel présents.
Un échec bloque la propagation vers la couche suivante.

Conséquence sur les scripts : **l'ingestion ne juge plus la qualité**. Le
`sys.exit(1)` actuel de `run_collection.py` sur les gènes incomplets est retiré du chemin
Airflow — la fonction `find_empty_genes` alimente la tâche `check_bronze`. Sans ça, une
collecte partielle mais déterministe serait relancée trois fois par le mécanisme de retry,
pour ~21 minutes d'appels d'API inutiles.

### 6.5 Politique de retry

`retries=3` avec backoff exponentiel et timeout par tâche, sauf pour les erreurs de
configuration (`NCBI_EMAIL` absent), qui lèvent une exception dédiée avec `retries=0` : une
erreur permanente ne doit pas être retentée.

---

## 7. Infrastructure Docker

`LocalExecutor`, metastore PostgreSQL. Ni Redis ni CeleryExecutor.

| Service | Limite mémoire |
|---|---|
| postgres | 1 Go |
| minio (+ init des buckets) | 1 Go |
| airflow-apiserver | 1,5 Go |
| airflow-scheduler | 2 Go |
| airflow-dag-processor | 1 Go |
| airflow-triggerer | 0,75 Go |
| **Réservé** | **~7,25 Go** |
| **Marge disponible pour les tâches** | **~4,75 Go** |

Cible : VPS 12 Go. Les buckets `bronze`, `silver` et `gold` sont créés automatiquement au
démarrage par un conteneur d'initialisation.

**Les dépendances d'ingestion sont isolées de celles d'Airflow.** Airflow impose un fichier
de contraintes épinglant `requests` et d'autres paquets ; installer la stack d'ingestion dans
la même image risque un conflit. L'isolation se fait par venv dédié dans l'image, ou par
`DockerOperator` si le besoin se confirme.

Les secrets (`NCBI_EMAIL`, identifiants MinIO) passent par variables d'environnement et
Connections Airflow, plus par un `.env` monté.

---

## 8. Modifications des scripts existants

| Fichier | Changement | Logique métier |
|---|---|---|
| `config.py` | `LAKE_URI` en variable d'environnement, défaut `file://` | inchangée |
| `clinvar.py` | URL de l'archive versionnée paramétrable par `ds` | inchangée ; `filter_clinvar` n'est plus appelé en Bronze |
| `hpo.py` | URL de release versionnée paramétrable | inchangée |
| `download.py` | vérification du `Content-Length` après téléchargement | inchangée |
| `medgen.py`, `ncbi_gene.py` | aucun | inchangée |
| `orchestrate.py` | n'est plus appelé par le chemin Bronze | inchangée, tests conservés |

Les cinq scripts `ingest_*.py` sont de nouveaux wrappers minces : ils analysent
`--logical-date`, `--genes` et `--lake-uri`, puis appellent les fonctions existantes.

`scripts/run_collection.py` est conservé tel quel comme chemin d'exécution autonome hors
Airflow.

### Corrections de dépendances

- Ajout de `boto3` (client S3 vers MinIO) — absent aujourd'hui.
- Réépinglage de `polars` : la version `1.43.0` actuellement requise est **retirée (yanked)
  de PyPI**, ce qui peut casser une installation sans préavis.

---

## 9. La cinquième source : RefSeq

`src/ingestion/refseq.py` interroge `db=nuccore` via `esearch` puis `esummary`, avec les
filtres `srcdb_refseq[prop]` et `biomol_mrna[prop]`.

Objectif : constituer le **catalogue des transcrits de référence** — accession, version,
longueur, statut. Les variants ClinVar sont nommés en HGVS (`NM_000059.4:c.1234A>G`) ; la
normalisation HGVS promise en Silver a besoin de ce catalogue, qu'aucune autre source du
projet ne fournit.

Coût : environ 36 requêtes pour 18 gènes, une centaine d'enregistrements.

**Note terminologique.** La « GenBank » mentionnée dans le document de problématique désigne
en réalité NCBI Gene (`db=gene`), déjà implémenté : GenBank est une base de séquences, NCBI
Gene une base de métadonnées de gènes. Le guide de récupération des données du projet signale
déjà cette imprécision comme étant à corriger dans le mémoire. La tâche du DAG est donc
nommée `ingest_ncbi_gene`, et `ingest_refseq` est la véritable source de séquences, ajoutée
pour un besoin identifié.

---

## 10. Les stubs de transformation

`src/transformations/bronze_to_silver.py` et `silver_to_gold.py` exposent leur signature et
documentent leur contrat d'entrée/sortie, puis lèvent
`NotImplementedError("moteur de transformation non arbitré")`.

Les tâches Airflow correspondantes existent et sont câblées : le DAG est complet et lisible
dès maintenant, et échoue explicitement à l'endroit prévu plutôt que silencieusement.

---

## 11. Stratégie de test

La propriété à préserver est que **la logique métier se teste sans infrastructure**. Les 63
tests existants tournent en 1,7 s sans réseau ; ils doivent rester verts et rapides.

- Les tests existants ne sont pas modifiés. `config.py` conserve son comportement par défaut
  (`file://`), donc `test_config.py` reste valide.
- Nouveaux tests unitaires : `storage.py` (écriture atomique, manifest, `_SUCCESS`),
  `refseq.py` (parsing des réponses, cas vide), résolution des URI `file://` et `s3://`.
- Tests d'intégration du stockage objet contre un MinIO éphémère, marqués et exclus de la
  passe rapide.
- Les DAGs sont couverts par un test d'import et de validité de graphe (absence de cycle,
  dépendances attendues), sans exécution de tâche.

---

## 12. Points ouverts, différés sciemment

- **Moteur de transformation Silver/Gold** — non arbitré. Le format Delta est compatible avec
  tous les candidats, donc la décision reste entièrement ouverte.
- **Durcissement de l'ingestion** — checkpoint et reprise, batching des appels `esummary`
  (potentiel de division du volume d'appels par ~100), pagination. Reporté explicitement.
  Interaction à connaître : sans checkpoint, `retries=3` relance une collecte complète.
- **Déduplication HPO** — la source ne change que quelques fois par an ; beaucoup de
  partitions `dt=` seront identiques. Déduplication par version de release à décider.
- **Rétention et `VACUUM`** — politique de purge des versions Delta à définir.
- **Base vectorielle** — hors périmètre de cette étape.

---

## Annexe — Mesures effectuées pendant la conception

Toutes réalisées sur la machine de développement, sur les transformations réelles du projet.
Reproductibles, et exploitables dans le mémoire pour justifier les choix.

### Capacités Delta Lake sans Spark

Écriture ACID, `MERGE`, time-travel, schema enforcement, `OPTIMIZE`, `Z-ORDER`, `VACUUM`,
contraintes `CHECK`, historique auditable — toutes vérifiées, sur système de fichiers local
et sur MinIO. Empreinte de la stack : 436 Mo. MinIO au repos : 75 Mo de RAM.

### Limites mesurées de l'implémentation actuelle

| Mesure | Valeur |
|---|---|
| Coût mémoire de `build_gene_documents` | **4,71 Ko par ligne** (43 colonnes) |
| Extrapolation ClinVar complet | ~27 Go de RAM — impraticable |
| Refiltrage par gène, à volume constant | ×7,6 de 25 à 6 400 gènes |
| Taille d'un JSON de sortie | 6,5 Mo pour un gène de 4 000 variants |

### Comparaison des moteurs, à titre indicatif

Chaîne complète (éclatement multi-gènes, filtre panel, déduplication, extraction regex,
agrégation), même machine, mêmes fichiers Parquet.

| Lignes | Moteur vectorisé mono-nœud | PySpark 4.2 (démarrage + transfo) |
|---|---|---|
| 100 000 | 0,11 s | 30,4 s |
| 1 000 000 | 0,29 s | 37,7 s |
| 5 000 000 | 1,84 s | 41,3 s |
| RAM à 5 M lignes | 928 Mo | 1 770 Mo |

Le coût marginal par ligne du moteur mono-nœud reste inférieur à celui de Spark même à
5 millions de lignes. Point de bascule identifié en faveur de Spark : les traitements Python
par ligne au-delà d'environ 200 000 éléments, où la parallélisation de l'UDF l'emporte sur
le coût de démarrage de la JVM (15 à 17 s par session).

Ces chiffres sont fournis comme éléments d'arbitrage ; **le choix du moteur reste ouvert.**
