# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This is stage 1 (data collection / RAW layer) of a larger genomics RAG pipeline:
**collecte (APIs) → pipeline Bronze/Silver/Gold (médaillon) → RAG (chunking, embeddings,
vector store, LLM) → web app**. Only the collection stage exists so far — do not build ahead
into normalization or RAG concerns; that boundary is intentional (see "Known limitations"
below, which lists issues deliberately deferred to the next stage).

This stage collects raw data for a fixed panel of 18 genes (`ALL_GENES` in
`src/ingestion/config.py`) — 12 hereditary breast cancer genes + 6 sickle cell disease /
HbF-modifier genes — from four public sources, and writes one JSON document per gene to
`data/raw/`.

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

- `pytest.ini` sets `pythonpath = src`, so tests import as `from ingestion.xxx import ...`
  (no package install needed).
- `NCBI_EMAIL` is required (NCBI E-utilities policy); real secrets go only in `.env`
  (gitignored), never in `.env.example`. Leave `NCBI_API_KEY` empty if you don't have one —
  a fake key would push the rate limiter into fast mode and cause errors mid-run.
- `run_collection.py` makes real network calls and is not covered by automated tests; its
  correctness relies on the unit-tested functions in `src/ingestion/`.
- First run: ~4 minutes (downloads the 440 MB ClinVar bulk + ~1,200 NCBI calls). The script
  exits with code 1 if any gene ends up with no variants and no NCBI Gene metadata.

## Architecture

Each of the four sources is one module in `src/ingestion/`, and `orchestrate.py` assembles
their outputs into per-gene documents. `scripts/run_collection.py` is the only orchestration
entry point (a thin CLI wrapper) — it calls each module in sequence:

1. **`clinvar.py`** — downloads the ClinVar bulk file (`variant_summary.txt.gz`, shared/cached,
   ~440 MB) via `download.py`, then uses polars to filter it to the gene panel and dedupe by
   `#AlleleID`.
2. **`ncbi_gene.py`** + **`medgen.py`** — use `http_client.NcbiClient` (esearch + esummary
   against NCBI E-utilities) to fetch gene metadata and disease/phenotype concepts.
   `medgen.py` also extracts MedGen CUIs from ClinVar's `PhenotypeIDS` field and parses the
   `conceptmeta` XML blob into structured fields.
3. **`hpo.py`** — downloads and parses the public HPO `genes_to_phenotype.txt` flat file (also
   via `download.py`). `phenotype.hpoa` (disease-centric annotations) is deliberately not
   downloaded — nothing consumes it without a disease→gene join that doesn't exist yet.
4. **`orchestrate.py`** — joins all four sources per gene into one document; `find_empty_genes`
   flags genes missing variants or gene metadata (used by the CLI to decide the exit code).

Shared infrastructure:
- **`http_client.py`** — `NcbiClient` (esearch/esummary, retry on 429/5xx via `urllib3.Retry`)
  and `RateLimiter`, which throttles calls to respect NCBI's global rate limit (faster with an
  API key). Both ClinVar and NCBI Gene/MedGen calls go through this client's retry/rate-limit
  logic.
- **`download.py`** — generic streamed download to a `.part` file with atomic rename, so a
  partial download is never mistaken for a complete, cacheable one. Shared by both the
  ClinVar bulk and the HPO flat file — downloads are skipped if the destination already
  exists (unless `--refresh`/`force=True`).
- **`config.py`** — gene panel (`ALL_GENES`), path constants (anchored to the repo root via
  `Path(__file__).resolve().parents[2]`, independent of CWD), and E-utilities constants.

### Output contract (`data/raw/{GENE}.json`)

This is the interface handed to the next stage (Bronze). Each document has: `gene_symbol`,
`gene_info` (raw NCBI Gene esummary), `variants` (raw ClinVar rows, original 43 columns),
`medgen_concepts` (raw + derived fields from `conceptmeta`), `hpo_terms`, and `_provenance`
(collection timestamp + source versions).

### Known limitations (intentionally deferred to Bronze, not to fix here)

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

## Data directories

`data/external/` (downloaded source files) and `data/raw/` (per-gene output) are gitignored
except for `.gitkeep`; regenerate their contents by running the collection script rather than
expecting them to be present in a fresh checkout.
