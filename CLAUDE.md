# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This repo holds the data engineering side of a genomics RAG pipeline:
**collecte (APIs) → médaillon `raw` → `bronze` → `silver` → `gold` → RAG (chunking,
embeddings, vector store, LLM) → web app**. What exists today: the collection code
(`src/ingestion/`), ingestion scripts that write the `raw` layer, the Airflow DAGs and Docker
stack that orchestrate them, and documented **stubs** for the `raw → bronze → silver → gold`
transformations. Those transformations are sub-projects B, C and D of
`docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md`; do not implement
them, or anything RAG-side, outside their own spec and plan.

This stage collects raw data for a fixed panel of 18 genes (`ALL_GENES` in
`src/ingestion/config.py`) — 12 hereditary breast cancer genes + 6 sickle cell disease /
HbF-modifier genes. The legacy CLI `scripts/run_collection.py` collects four public sources
and writes one JSON document per gene to `data/raw/` (sections below); the medallion pipeline
instead writes per-source partitions to the `raw` layer through `scripts/ingest_*.py`.

Project docs and requirements notes (in French) live in `fichiers de base /` and
`docs/superpowers/plans/`.

## Commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt      # runtime + test deps

cp .env.example .env                     # then fill in NCBI_EMAIL (and optionally NCBI_API_KEY)

pytest -q                                 # run the full test suite
pytest tests/ingestion/test_medgen.py -q  # run a single test file
pytest tests/ingestion/test_medgen.py::test_name -q  # run a single test

python scripts/run_collection.py            # reuses the already-downloaded ClinVar bulk
python scripts/run_collection.py --refresh   # forces re-download of source files
```

- `pytest.ini` sets `pythonpath = src .`, so tests import as `from ingestion.xxx import ...`
  (no package install needed); the `.` makes the root-level `scripts` and `dags` packages
  importable too (`from scripts.ingest_clinvar import ...`, `from dags.common.dates import ...`).
- `NCBI_EMAIL` is required (NCBI E-utilities policy); real secrets go only in `.env`
  (gitignored), never in `.env.example`. Leave `NCBI_API_KEY` empty if you don't have one —
  a fake key would push the rate limiter into fast mode and cause errors mid-run.
- `run_collection.py` makes real network calls and is not covered by automated tests; its
  correctness relies on the unit-tested functions in `src/ingestion/`.
- First run: ~4 minutes (downloads the 440 MB ClinVar bulk + ~1,200 NCBI calls). The script
  exits with code 1 if any gene ends up with no variants and no NCBI Gene metadata.

## Architecture

Each source is one module in `src/ingestion/`. Two entry points use them:
`scripts/run_collection.py`, the legacy CLI (a thin wrapper) where `orchestrate.py` assembles
four sources into per-gene documents; and the medallion pipeline, where `scripts/ingest_*.py`
write `raw` partitions and `dags/` orchestrates them. The legacy CLI calls each module in
sequence:

1. **`clinvar.py`** — downloads the ClinVar bulk file (`variant_summary.txt.gz`, shared/cached,
   ~440 MB) via `download.py`, then uses polars to filter it to the gene panel and dedupe by
   `#AlleleID`.
2. **`ncbi_gene.py`** + **`medgen.py`** — use `http_client.NcbiClient` (esearch + esummary
   against NCBI E-utilities) to fetch gene metadata and disease/phenotype concepts.
   `medgen.py` also extracts MedGen CUIs from ClinVar's `PhenotypeIDS` field and parses the
   `conceptmeta` XML blob into structured fields.
3. **`hpo.py`** — downloads and parses the public HPO `genes_to_phenotype.txt` flat file (also
   via `download.py`), then enriches each row with `definition`/`synonyms`/`xrefs` fetched
   from the `ontology.jax.org/api/hp/terms` REST API (keyless, batched — up to
   `HP_TERMS_BATCH_SIZE` HPO IDs per call, since the API caps its `filter` query param at 250
   chars). `phenotype.hpoa` (disease-centric annotations) is deliberately not downloaded —
   nothing consumes it without a disease→gene join that doesn't exist yet.
4. **`orchestrate.py`** — joins all four sources per gene into one document; `find_empty_genes`
   flags genes missing variants or gene metadata (used by the CLI to decide the exit code).

5. **`refseq.py`** — RefSeq transcript catalogue per gene (esearch + esummary on `nuccore`),
   needed by the Silver HGVS normalisation; medallion pipeline only.

Shared infrastructure:
- **`storage.py`** — medallion lake I/O on `file://` or `s3://` (MinIO): partition URIs,
  put/get/stream/delete, manifests, and the partition protocol `begin_partition` → data →
  manifest → `_SUCCESS`, checked by `assert_partitions_complete`.
- **`jsonl.py`** — gzipped JSONL serialisation of raw API responses for the `raw` layer.
- **`errors.py`** — `ConfigurationError`, a permanent error that DAGs turn into a non-retried
  Airflow failure.
- **`http_client.py`** — `NcbiClient` (esearch/esummary, retry on 429/5xx via `urllib3.Retry`)
  and `RateLimiter`, which throttles calls to respect NCBI's global rate limit (faster with an
  API key). Also exports `build_retrying_session()`, the retry-configured `requests.Session`
  factory shared by `NcbiClient` and `hpo.py`'s HPO-terms API calls.
- **`download.py`** — generic streamed download to a `.part` file with atomic rename, so a
  partial download is never mistaken for a complete, cacheable one. Shared by both the
  ClinVar bulk and the HPO flat file — downloads are skipped if the destination already
  exists (unless `--refresh`/`force=True`).
- **`config.py`** — gene panel (`ALL_GENES`), path constants (anchored to the repo root via
  `Path(__file__).resolve().parents[2]`, independent of CWD), and E-utilities constants.

### Legacy output contract (`data/raw/{GENE}.json`)

Output of `scripts/run_collection.py` only — the medallion pipeline does not consume it. Each document has: `gene_symbol`,
`gene_info` (raw NCBI Gene esummary), `variants` (raw ClinVar rows, original 43 columns),
`medgen_concepts` (raw + derived fields from `conceptmeta`), `hpo_terms` (each row enriched
with `definition`/`synonyms`/`xrefs`), and `_provenance` (collection timestamp + source
versions).

### Known limitations (intentionally deferred to the Silver layer, not to fix here)

- `variants` is ClinVar column names as-is (e.g. `#AlleleID`, `RS# (dbSNP)`) — no renaming.
- `filter_clinvar` does exact matching on `GeneSymbol`, so ~0.3% of ClinVar rows where multiple
  genes are joined by `;` are dropped (mostly ATM, PTEN, HBB, BRCA1, MYB).
- MedGen singular fields (`mim_number`, `mode_inheritance`, `clinical_summary`) keep only the
  first occurrence; consume the plural fields (`mim_numbers`, `modes_inheritance`,
  `definitions`) for the exhaustive view. The raw `conceptmeta` XML is preserved as source of
  truth.
- A `medgen_concepts` entry can be just `{"conceptid": "..."}` — an unresolvable CUI, treated
  as a legitimate "unknown concept", not an error.
- Empty `hpo_terms` for `HBS1L` and `MYB` is expected (GWAS loci absent from HPO annotations,
  not a failed collection) — `find_empty_genes` deliberately does not check for this.
- `definition`/`synonyms`/`xrefs` on an `hpo_terms` row can be empty (`""`/`[]`) when
  `ontology.jax.org` no longer recognizes that HPO ID (retired/merged term) — treated the same
  way as an unresolvable MedGen CUI, not an error.

## Data directories

`data/external/` (downloaded source files) and `data/raw/` (per-gene output) are gitignored
except for `.gitkeep`; regenerate their contents by running the collection script rather than
expecting them to be present in a fresh checkout. `data/lake/` (gitignored) is the local
medallion lake — one sub-directory per layer — used when `LAKE_URI` is unset.

## Orchestration — Airflow 3 (NiFi : alternative évaluée, écartée)

**NiFi est retiré du chemin d'implémentation.** Le dossier `nifi/` est conservé comme
alternative implémentée, mesurée et écartée : ses apports ici (déclenchement planifié,
routage succès/échec, journalisation) sont un sous-ensemble strict de ceux d'Airflow,
pour un coût mesuré de 1,37 Gio de RAM au repos. Chiffres : `docs/choix_contexte.md`.

**Architecture en quatre couches** (spec : `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md`) :
`raw` (format de la source) → `bronze` (Parquet) → `silver` (Delta) → `gold/rag` et
`gold/analytique` (Delta), chacune dans un bucket MinIO. Moteur : Polars.

- `scripts/ingest_*.py` écrivent uniquement en `raw`.
- `src/transformations/` contient les passages entre couches : `bronze_to_silver` et
  `quality_check_silver` (sous-projet C) livrés sur cette branche ; `raw_to_bronze`
  (sous-projet B) reste un stub (livré sur une branche séparée non encore fusionnée) ;
  `silver_to_gold_rag`/`silver_to_gold_analytique` restent des stubs (sous-projet D).
- `dags/` : un DAG d'acquisition mensuel pour les sources partagées, un DAG par panel.
- `docker/` et `docker-compose.yml` : Airflow 3, PostgreSQL, MinIO.

**Règle non négociable :** la logique métier vit dans `src/` et `scripts/`, testée sans
infrastructure ; Airflow ne fait qu'appeler des fonctions ; MinIO ne fait que stocker.

**Deux passes de tests :** `pytest -q` (logique, moins de 3 s, sans réseau ni conteneur)
et `pytest tests_airflow -q` (structure des DAGs ; séparée parce que `import airflow.sdk`
prend à lui seul ~3 s).
