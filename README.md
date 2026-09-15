# Système RAG génomique — Étape 1 : collecte de données (couche RAW)

Première étape d'un pipeline de data engineering pour un système RAG d'interrogation de
variants ADN. Cette étape **collecte** les données brutes depuis quatre sources publiques et
les assemble en un document JSON par gène. Elle ne fait **que** cela : la normalisation
(architecture médaillon Bronze/Silver/Gold), l'indexation et le RAG sont les étapes suivantes.

## Sources collectées

| Source | Contenu | Accès |
|---|---|---|
| **ClinVar** | Variants et leur signification clinique | Fichier bulk FTP (`variant_summary.txt.gz`, ~440 Mo) |
| **NCBI Gene** | Métadonnées du gène (nom, description, localisation) | E-utilities (esearch + esummary) |
| **MedGen** | Concepts maladie, MIM, mode d'hérédité, features HPO | E-utilities (esearch + esummary) |
| **HPO** | Termes phénotypiques associés au gène, enrichis de leur definition/synonyms/xrefs | Fichier plat public (`genes_to_phenotype.txt`) + API `ontology.jax.org/api/hp/terms` (sans clé, par lots) |

Panel : **18 gènes** — cancer du sein héréditaire (12) + drépanocytose et modificateurs (6).
Voir `src/ingestion/config.py`.

## Prérequis

- Python 3.12
- Une adresse email (obligatoire, exigée par NCBI E-utilities)
- Une clé API NCBI (recommandée : 10 req/s au lieu de 3 — https://account.ncbi.nlm.nih.gov/settings/)

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt   # runtime + outils de test

cp .env.example .env                  # puis renseigner NCBI_EMAIL (et NCBI_API_KEY)
```

⚠️ Les vraies valeurs vont **uniquement** dans `.env` (gitignoré). Ne jamais les mettre dans
`.env.example`, qui est suivi par git.

## Lancer la collecte

```bash
python scripts/run_collection.py            # réutilise le bulk ClinVar déjà téléchargé
python scripts/run_collection.py --refresh  # force le retéléchargement des fichiers sources
```

Premier run : ~4 minutes (télécharge 440 Mo de ClinVar + ~1 200 appels NCBI). Les runs
suivants réutilisent les fichiers déjà présents dans `data/external/`. Le script écrit un
fichier par gène dans `data/raw/` et **sort en code 1** si un gène ressort sans variants ni
métadonnées (symbole invalide ou collecte partielle).

## Tests

```bash
pytest -q
```

Le script `run_collection.py` fait de vrais appels réseau et n'est pas testé automatiquement ;
sa correction repose sur les fonctions unitaires des modules `src/ingestion/`.

## Lancer le pipeline médaillon

Deux passes de tests couvrent le pipeline complet (ingestion + orchestration Airflow) :

```bash
venv/bin/pytest -q               # logique, sans infrastructure
venv/bin/pytest tests_airflow -q # structure des DAGs, nécessite apache-airflow
```

Démarrer la stack (Airflow 3 + PostgreSQL + MinIO, quatre buckets du médaillon) :

```bash
cp .env.docker.example .env.docker
# puis renseigner .env.docker, notamment :
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # -> AIRFLOW_JWT_SECRET

docker compose --env-file .env.docker up -d --build
```

- Airflow est sur `http://localhost:8080` (utilisateur `admin`, mot de passe dans
  `/opt/airflow/simple_auth_manager_passwords.json.generated` du conteneur
  `airflow-apiserver`).
- La console MinIO est sur `http://localhost:<MINIO_CONSOLE_PORT>` (9001 par défaut).

### État volontaire du pipeline

Les passages `raw_to_bronze`, `bronze_to_silver`, `quality_check_silver`,
`silver_to_gold_rag` et `silver_to_gold_analytique` échouent explicitement, en nommant le
sous-projet qui les implémentera. Conséquence : tant que le sous-projet B n'est pas livré,
`check_bronze_shared` ne réussit pas, l'Asset n'est pas publié, et les DAGs de panel ne se
déclenchent pas automatiquement.

Pour exercer l'ingestion par panel, les déclencher à la main en indiquant la date des
sources partagées déjà déposées :

```bash
docker compose --env-file .env.docker exec airflow-scheduler \
  airflow dags trigger dag_genomic_pipeline_brca --conf '{"sources_date": "2026-09-01"}'
```

La date est résolue, les quatre ingestions et `check_raw` s'exécutent, puis le run s'arrête
à `raw_to_bronze`.

Un déclenchement manuel du DAG d'acquisition demande `--logical-date AAAA-MM-JJ` : dans
Airflow 3, un run manuel n'a pas de date logique sans cette option.

```bash
docker compose --env-file .env.docker exec airflow-scheduler \
  airflow dags trigger dag_acquisition_sources --logical-date 2026-09-01
```

## Lancer la collecte via NiFi (optionnel)

`nifi/` fait tourner `run_collection.py` comme un flow Apache NiFi planifié (cron
quotidien, routage succès/échec, journalisation) plutôt qu'un lancement manuel — voir
`nifi/README.md`. NiFi ne fait qu'orchestrer cette étape : la logique de collecte reste
intégralement dans `src/ingestion/`, inchangée et testée par `pytest` comme ci-dessus.

## Schéma d'un `data/raw/{GENE}.json`

Contrat de sortie de cette étape — c'est l'entrée de l'étape 2. Chaque document a ces clés :

| Clé | Type | Contenu |
|---|---|---|
| `gene_symbol` | `str` | Symbole du gène (ex. `"HBB"`) |
| `gene_info` | `dict` | esummary NCBI Gene brut (nom, description, `maplocation`, `summary`…) |
| `variants` | `list[dict]` | Lignes ClinVar brutes, **43 colonnes d'origine** |
| `medgen_concepts` | `list[dict]` | Concepts MedGen, bruts + champs dérivés du `conceptmeta` |
| `hpo_terms` | `list[dict]` | `{gene_symbol, hpo_id, hpo_name, definition, synonyms, xrefs}` |
| `_provenance` | `dict` | Date de collecte (UTC) et versions des sources |

### Points à connaître avant de consommer cette couche

- **`variants` porte les noms de colonnes ClinVar d'origine**, `#AlleleID` (avec le `#`),
  `RS# (dbSNP)` (avec espace et parenthèses)… Prévoir un renommage systématique en Bronze.
- **`variants` est incomplet d'environ 0,3 %** : `filter_clinvar` fait une correspondance
  exacte sur `GeneSymbol` et ignore donc les lignes ClinVar où plusieurs gènes sont joints par
  `;` (~270 associations, surtout ATM, PTEN, HBB, BRCA1, MYB). Les récupérer (`split(";")` +
  explode) est une décision de modélisation qui appartient à Bronze.
- **Champs MedGen singuliers non exhaustifs** : `mim_number`, `mode_inheritance`,
  `clinical_summary` ne gardent que la **première** occurrence. Un concept peut en avoir
  plusieurs (beta Thalassemia a 2 MIM et 2 modes d'hérédité). Consommer les pluriels
  `mim_numbers`, `modes_inheritance`, `definitions`. Le XML `conceptmeta` brut est conservé
  comme source de vérité.
- **`medgen_concepts` peut contenir `{"conceptid": "..."}` seul** : CUI non résolvable par
  MedGen (comportement correct et voulu), à traiter comme « concept inconnu ».
- **`hpo_terms` vide est légitime pour `HBS1L` et `MYB`** (loci GWAS absents des annotations
  HPO, pas des gènes mendéliens) — ce n'est pas une collecte ratée.
- **`definition`/`synonyms`/`xrefs` peuvent être vides** sur une ligne `hpo_terms` : l'API
  `ontology.jax.org` ne les fournit pas pour un terme qu'elle ne reconnaît plus (retiré/fusionné
  côté HPO) — traiter comme un enrichissement manquant, pas une erreur.

## Structure

```
src/ingestion/
  config.py        panel de gènes, chemins, constantes
  download.py      téléchargement atomique avec cache (partagé ClinVar/HPO)
  http_client.py   RateLimiter + NcbiClient (retry, rate limit)
  clinvar.py       download + filtrage du bulk ClinVar
  ncbi_gene.py     fetch_gene_info
  medgen.py        extraction CUI, fetch concept, parsing conceptmeta
  hpo.py           download + parsing genes_to_phenotype, enrichissement via l'API HPO
  orchestrate.py   assemblage des 4 sources en un document par gène
scripts/
  run_collection.py   point d'entrée CLI
data/
  external/        fichiers sources téléchargés (gitignoré)
  raw/             documents produits, un par gène (gitignoré)
```
