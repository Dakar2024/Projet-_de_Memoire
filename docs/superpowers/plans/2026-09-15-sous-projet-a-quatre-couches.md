# Sous-projet A — quatre couches, DAGs et infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Renommer la couche d'atterrissage en `raw`, terminer l'ingestion (MedGen, termes HPO), câbler les quatre couches dans les DAGs Airflow avec des transformations en stubs, et livrer la stack Docker.

**Architecture :** Les tâches 1 à 7 du plan du 2026-09-04 ont livré l'ingestion sous le nom de couche `bronze` ; ce plan la renomme `raw` puis reprend ses tâches 8 à 12, réalignées sur quatre couches. La logique reste dans `src/` et `scripts/`, testée sans infrastructure ; Airflow 3 n'appelle que des fonctions. Les passages `raw → bronze → silver → gold` sont câblés et échouent explicitement : ils seront implémentés par les sous-projets B, C et D.

**Tech Stack :** Python 3.12, Airflow 3.3.1 (`airflow.sdk`), MinIO (S3), boto3, PostgreSQL 16, Docker Compose, pytest + responses.

**Spec :** `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md` (amende `docs/superpowers/specs/2026-09-04-pipeline-medaillon-airflow-minio-design.md`, qui reste valable pour tout ce qu'elle ne remplace pas).

**Remplace :** les tâches 8 à 12 de `docs/superpowers/plans/2026-09-04-pipeline-medaillon-airflow-minio.md`.

## Global Constraints

- Quatre couches, quatre buckets MinIO : `raw`, `bronze`, `silver`, `gold`. `gold` contient les préfixes `rag/` et `analytique/`.
- `config.py` expose `RAW = "raw"`, `BRONZE = "bronze"`, `SILVER = "silver"`, `GOLD = "gold"`.
- Les scripts d'ingestion écrivent **uniquement** en `raw`. Chacun a un test qui affirme un chemin `…/raw/…`.
- `raw` est strictement brut : aucun filtrage, typage, parsing ni dédoublonnage. Le bulk ClinVar est non filtré, le XML `conceptmeta` reste une chaîne.
- Aucune logique métier dans un DAG. Les DAGs appellent des fonctions de `src/` et `scripts/`.
- Les transformations restent des stubs qui lèvent `NotImplementedError` en nommant le sous-projet qui les implémentera (B, C ou D). Ne pas importer `polars`, `deltalake`, `pyspark` ni `pandas` dans `src/transformations/` ni dans `dags/`.
- **Deux passes de tests.** `venv/bin/pytest -q` exécute la logique métier, en moins de 3 s, sans réseau ni conteneur (dossier `tests/`). Les tests qui importent Airflow vivent dans `tests_airflow/` et se lancent par `venv/bin/pytest tests_airflow -q` — mesuré : `import airflow.sdk` prend à lui seul 3,3 s, ce qui ferait sortir la passe rapide de son budget.
- Airflow 3.3.1 exactement. Imports depuis `airflow.sdk` et `airflow.sdk.exceptions`.
- Commentaires, docstrings et messages en français. Imports en tête de fichier (E402).
- Le bulk ClinVar se lit en flux (`open_stream` → `GzipFile` → `TextIOWrapper` → `DictReader`), jamais matérialisé en mémoire.

## Hors périmètre de ce plan

- **Implémentation des transformations** : sous-projets B (`raw → bronze`), C (`bronze → silver`) et D (`silver → gold`), chacun avec sa propre spec.
- **Rejeu interrompu en `raw`** (spec §8) : un rejeu qui échoue entre l'écriture des données et `finalize_partition` peut laisser un `_SUCCESS` ancien. Ce plan ne le traite pas ; la question est reportée au sous-projet B, qui écrira aussi des partitions `bronze` sujettes au même problème, afin de la régler une seule fois pour les deux couches.
- **Deltalake** n'est pas ajouté aux dépendances : aucune tâche de ce plan n'écrit de table Delta.

---

## Structure des fichiers

**Modifiés :** `src/ingestion/config.py`, `src/ingestion/storage.py`, docstrings de `src/ingestion/{clinvar,jsonl,refseq}.py`, les quatre `scripts/ingest_*.py` livrés, leurs tests, `tests/ingestion/test_config.py`, `tests/ingestion/test_storage.py`, `requirements-dev.txt`, `README.md`, `CLAUDE.md`, `nifi/README.md`, `.gitignore`.

**Créés :**

| Fichier | Responsabilité |
|---|---|
| `scripts/ingest_medgen.py` | Concepts MedGen du panel, dépôt en `raw` |
| `scripts/ingest_hpo_terms.py` | Détails des termes HPO du panel, dépôt en `raw` |
| `src/transformations/raw_to_bronze.py` | Stub — sous-projet B |
| `src/transformations/bronze_to_silver.py` | Stub — sous-projet C |
| `src/transformations/silver_to_gold_rag.py` | Stub — sous-projet D |
| `src/transformations/silver_to_gold_analytique.py` | Stub — sous-projet D |
| `dags/common/panels.py` | Panels, sources partagées et par panel, Asset |
| `dags/dag_acquisition_sources.py` | DAG mensuel des sources partagées |
| `dags/dag_genomic_pipeline.py` | DAGs par panel |
| `tests_airflow/` | Tests de structure des DAGs |
| `docker-compose.yml`, `docker/airflow/Dockerfile`, `docker/minio/create-buckets.sh`, `.env.docker.example` | Infrastructure |

---

### Task 1 (A1): Renommer la couche d'atterrissage `bronze` en `raw`

**Files:**
- Modify: `src/ingestion/config.py:19`
- Modify: `scripts/ingest_clinvar.py`, `scripts/ingest_hpo_files.py`, `scripts/ingest_ncbi_gene.py`, `scripts/ingest_refseq.py`
- Modify: `src/ingestion/clinvar.py:50`, `src/ingestion/jsonl.py:13`, `src/ingestion/storage.py:23,144`, `src/ingestion/refseq.py:20`
- Test: `tests/ingestion/test_config.py`, `tests/ingestion/test_storage.py`, `tests/scripts/test_ingest_clinvar.py`, `tests/scripts/test_ingest_hpo_files.py`, `tests/scripts/test_ingest_ncbi_gene.py`, `tests/scripts/test_ingest_refseq.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `ingestion.config.RAW = "raw"`. `BRONZE` continue d'exister et désigne désormais la couche Parquet. Les quatre scripts écrivent sous `raw/<source>/dt=…`.

**Pourquoi c'est une tâche à part.** La constante `BRONZE` ne disparaît pas : elle change de sens. Un `partition_uri(BRONZE, …)` oublié ne lèverait aucune erreur et déposerait silencieusement des données brutes dans le bucket `bronze`. Les tests de chemin sont ce qui protège ce renommage — ils changent donc en premier.

- [ ] **Step 1: Mettre les tests au nouveau contrat (ils doivent échouer)**

```bash
sed -i 's#{lake}/bronze/#{lake}/raw/#' \
  tests/scripts/test_ingest_clinvar.py tests/scripts/test_ingest_hpo_files.py \
  tests/scripts/test_ingest_ncbi_gene.py tests/scripts/test_ingest_refseq.py
sed -i 's/Bronze est strictement brut/La couche raw est strictement brute/' tests/scripts/test_ingest_clinvar.py
sed -i 's/check_bronze/check_raw/g' tests/scripts/test_ingest_refseq.py
sed -i 's/check_bronze/check_raw/g; s/bronze/raw/g' tests/ingestion/test_storage.py
```

Dans `tests/ingestion/test_config.py`, remplacer la ligne d'import :

```python
from ingestion.config import BRONZE, GOLD, SILVER, current_lake_uri
```

par :

```python
from ingestion.config import BRONZE, GOLD, RAW, SILVER, current_lake_uri
```

et remplacer le test `test_layer_names_are_the_three_medallion_buckets` par :

```python
def test_layer_names_are_the_four_medallion_buckets():
    assert (RAW, BRONZE, SILVER, GOLD) == ("raw", "bronze", "silver", "gold")
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest -q`
Expected: FAIL — `ImportError: cannot import name 'RAW'` dans `test_config.py`, et des `AssertionError` sur les chemins `…/bronze/…` attendus `…/raw/…` dans les tests de scripts.

- [ ] **Step 3: Ajouter la constante `RAW`**

Dans `src/ingestion/config.py`, remplacer :

```python
# Couches du médaillon. Sur MinIO, chaque couche est un bucket ; en local, un
# sous-dossier de DEFAULT_LAKE_DIR.
BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"
```

par :

```python
# Couches du médaillon : raw (format de la source), bronze (Parquet), silver et
# gold (Delta). Sur MinIO, chaque couche est un bucket ; en local, un sous-dossier
# de DEFAULT_LAKE_DIR.
RAW = "raw"
BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"
```

- [ ] **Step 4: Repointer les scripts sur `RAW`**

```bash
sed -i 's/from ingestion.config import BRONZE, DATA_EXTERNAL_DIR/from ingestion.config import DATA_EXTERNAL_DIR, RAW/' \
  scripts/ingest_clinvar.py scripts/ingest_hpo_files.py
sed -i 's/^from ingestion.config import BRONZE$/from ingestion.config import RAW/' \
  scripts/ingest_ncbi_gene.py scripts/ingest_refseq.py
sed -i 's/partition_uri(BRONZE,/partition_uri(RAW,/' scripts/ingest_*.py
sed -i 's/check_bronze/check_raw/g; s/ en Bronze/ dans la couche raw/g' scripts/ingest_*.py src/ingestion/refseq.py
sed -i "s/ce qu'exige le contrat Bronze\./ce qu'exige le contrat de la couche raw./" src/ingestion/jsonl.py
sed -i 's#(`s3://bronze`)#(`s3://raw`)#; s/Décrit une partition Bronze de façon/Décrit une partition de façon/' src/ingestion/storage.py
sed -i 's/appartient à la couche Bronze, pas à la couche RAW\./appartient à la couche Silver, pas à la couche raw./' src/ingestion/clinvar.py
```

- [ ] **Step 5: Vérifier qu'il ne reste aucune référence à l'ancienne couche**

Run: `grep -rn -i "bronze" scripts/ src/ingestion/ tests/scripts/ tests/ingestion/`
Expected: exactement quatre lignes — dans `src/ingestion/config.py`, la ligne de commentaire mentionnant `bronze (Parquet)` et la constante `BRONZE = "bronze"` ; dans `tests/ingestion/test_config.py`, l'import et l'assertion des quatre couches. Aucune ligne dans `scripts/`, `tests/scripts/` ni `tests/ingestion/test_storage.py`. Si un script apparaît, le renommage est incomplet.

- [ ] **Step 6: Vérifier que la suite repasse**

Run: `venv/bin/pytest -q`
Expected: PASS, 107 passed, 1 deselected, en moins de 3 s

- [ ] **Step 7: Commit**

```bash
git add src/ingestion/ scripts/ tests/
git commit -m "refactor: rename the landing layer from bronze to raw"
```

---

### Task 2 (A2): Ingestion MedGen et termes HPO en `raw`

**Files:**
- Create: `scripts/ingest_medgen.py`
- Create: `scripts/ingest_hpo_terms.py`
- Test: `tests/scripts/test_ingest_medgen.py`, `tests/scripts/test_ingest_hpo_terms.py`

**Interfaces:**
- Consumes: `ingestion.config.RAW` (Task A1) ; `ingestion.storage.open_stream/get_bytes/put_bytes/partition_uri/build_manifest/finalize_partition` ; `ingestion.medgen.extract_medgen_cuis/fetch_medgen_concept` ; `ingestion.hpo.HP_TERMS_URL/parse_genes_to_phenotype/fetch_hpo_term_details` ; `ingestion.jsonl.dumps_gzipped` ; `scripts.ingest_ncbi_gene.build_client`.
- Produces: `scripts.ingest_medgen.cuis_from_raw_clinvar(clinvar_partition: str, genes: list[str], client=None) -> list[str]` ; `scripts.ingest_medgen.ingest_medgen(logical_date: str, panel: str, genes: list[str], client: NcbiClient, lake_uri: str | None = None) -> str` ; `scripts.ingest_hpo_terms.ingest_hpo_terms(logical_date: str, panel: str, genes: list[str], lake_uri: str | None = None) -> str`.

- [ ] **Step 1: Écrire les tests MedGen**

Créer `tests/scripts/test_ingest_medgen.py` :

```python
import gzip
import json

import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.storage import get_bytes, partition_is_complete, put_bytes
from scripts.ingest_medgen import cuis_from_raw_clinvar, ingest_medgen

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

BULK = (
    "#AlleleID\tGeneSymbol\tPhenotypeIDS\n"
    "1\tHBB\tMedGen:C0002895,OMIM:603903\n"
    "2\tINCONNU\tMedGen:C9999999\n"
    "3\tHBB\tMedGen:C0002895\n"
)


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


def _seed_raw_clinvar(tmp_path) -> str:
    partition = f"file://{tmp_path}/lake/raw/clinvar/dt=2026-09-01"
    put_bytes(f"{partition}/variant_summary.txt.gz", gzip.compress(BULK.encode()))
    return partition


def _mock_one_concept():
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["287"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "287": {"conceptid": "C0002895", "conceptmeta": "<OMIM><MIM>603903</MIM></OMIM>"}
    }}, status=200)


def test_cuis_from_raw_clinvar_keeps_only_panel_genes(tmp_path):
    """La lecture du bulk pilote les appels d'API ; rien n'est persisté."""
    partition = _seed_raw_clinvar(tmp_path)

    assert cuis_from_raw_clinvar(partition, ["HBB"]) == ["C0002895"]


def test_cuis_from_raw_clinvar_deduplicates_in_order(tmp_path):
    partition = _seed_raw_clinvar(tmp_path)

    assert cuis_from_raw_clinvar(partition, ["HBB", "INCONNU"]) == [
        "C0002895",
        "C9999999",
    ]


@responses.activate
def test_ingest_medgen_writes_one_record_per_cui_in_raw(tmp_path):
    _seed_raw_clinvar(tmp_path)
    _mock_one_concept()
    lake = f"file://{tmp_path}/lake"

    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    assert partition == f"{lake}/raw/medgen/dt=2026-09-01/panel=sickle"
    raw = gzip.decompress(get_bytes(f"{partition}/concepts.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["cui"] for r in records] == ["C0002895"]
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_medgen_keeps_the_conceptmeta_xml_unparsed(tmp_path):
    """La couche raw est brute : l'aplatissement du XML appartient au Silver."""
    _seed_raw_clinvar(tmp_path)
    _mock_one_concept()
    lake = f"file://{tmp_path}/lake"

    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    record = json.loads(
        gzip.decompress(get_bytes(f"{partition}/concepts.jsonl.gz")).decode().splitlines()[0]
    )
    assert "mim_number" not in record["esummary"]
    assert record["esummary"]["conceptmeta"] == "<OMIM><MIM>603903</MIM></OMIM>"
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/scripts/test_ingest_medgen.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'scripts.ingest_medgen'`

- [ ] **Step 3: Implémenter `scripts/ingest_medgen.py`**

```python
"""Ingestion des concepts MedGen par panel dans la couche raw."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import RAW
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.medgen import extract_medgen_cuis, fetch_medgen_concept
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    open_stream,
    partition_uri,
    put_bytes,
)
from scripts.ingest_ncbi_gene import build_client

OBJECT_NAME = "concepts.jsonl.gz"
BULK_OBJECT = "variant_summary.txt.gz"


def cuis_from_raw_clinvar(
    clinvar_partition: str, genes: list[str], client=None
) -> list[str]:
    """Extrait les CUI MedGen du bulk ClinVar brut, pour les gènes du panel.

    MedGen a une dépendance de données sur ClinVar : les CUI viennent du champ
    `PhenotypeIDS`. Cette lecture pilote les appels d'API et ne persiste rien.

    Le bulk est parcouru en flux : 442 Mo compressés, ~4 Go décompressés. La chaîne
    `open_stream` -> `GzipFile` -> `TextIOWrapper` -> `DictReader` ne tient qu'une
    ligne à la fois en mémoire.
    """
    genes_set = set(genes)
    cuis: list[str] = []

    with open_stream(f"{clinvar_partition}/{BULK_OBJECT}", client=client) as raw:
        with gzip.GzipFile(fileobj=raw, mode="rb") as decompressed:
            reader = csv.DictReader(
                io.TextIOWrapper(decompressed, encoding="utf-8"), delimiter="\t"
            )
            for row in reader:
                if row.get("GeneSymbol") not in genes_set:
                    continue
                for cui in extract_medgen_cuis(row.get("PhenotypeIDS") or ""):
                    if cui not in cuis:
                        cuis.append(cui)
    return cuis


def ingest_medgen(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose les concepts MedGen du panel dans la couche raw, XML `conceptmeta` intact."""
    clinvar_partition = partition_uri(RAW, "clinvar", logical_date, lake_uri=lake_uri)
    cuis = cuis_from_raw_clinvar(clinvar_partition, genes)

    records = [
        {"cui": cui, "esummary": fetch_medgen_concept(client, cui)} for cui in cuis
    ]
    partition = partition_uri(RAW, "medgen", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="medgen",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=medgen",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les concepts MedGen dans la couche raw.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_medgen(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
```

- [ ] **Step 4: Vérifier que les tests MedGen passent**

Run: `venv/bin/pytest tests/scripts/test_ingest_medgen.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Écrire les tests des termes HPO**

Créer `tests/scripts/test_ingest_hpo_terms.py` :

```python
import gzip
import json

import responses

from ingestion.storage import get_bytes, partition_is_complete, put_bytes
from scripts.ingest_hpo_terms import ingest_hpo_terms

HP_TERMS = "https://ontology.jax.org/api/hp/terms"

FLAT = (
    "ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n"
    "3043\tHBB\tHP:0001903\tAnemia\n"
    "9999\tAUTRE\tHP:0000118\tPhenotypic abnormality\n"
)


def _seed_flat_file(tmp_path) -> str:
    lake = f"file://{tmp_path}/lake"
    put_bytes(f"{lake}/raw/hpo/dt=2026-09-01/genes_to_phenotype.txt", FLAT.encode())
    return lake


@responses.activate
def test_ingest_hpo_terms_enriches_only_the_panel_genes(tmp_path):
    """Le fichier plat est partagé entre panels : seuls les termes des gènes du
    panel demandé doivent être enrichis et déposés."""
    lake = _seed_flat_file(tmp_path)
    responses.add(responses.GET, HP_TERMS, json=[
        {"id": "HP:0001903", "definition": "A reduction in erythrocytes.",
         "synonyms": ["Low blood count"], "xrefs": ["UMLS:C0002871"]}], status=200)

    partition = ingest_hpo_terms("2026-09-01", "sickle", ["HBB"], lake_uri=lake)

    assert partition == f"{lake}/raw/hpo_terms/dt=2026-09-01/panel=sickle"
    raw = gzip.decompress(get_bytes(f"{partition}/hpo_terms.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["hpo_id"] for r in records] == ["HP:0001903"]
    assert records[0]["details"]["definition"] == "A reduction in erythrocytes."
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_hpo_terms_manifest_records_the_panel(tmp_path):
    lake = _seed_flat_file(tmp_path)
    responses.add(responses.GET, HP_TERMS, json=[], status=200)

    partition = ingest_hpo_terms("2026-09-01", "sickle", ["HBB"], lake_uri=lake)

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source"] == "hpo_terms"
    assert manifest["panel"] == "sickle"
```

- [ ] **Step 6: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/scripts/test_ingest_hpo_terms.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'scripts.ingest_hpo_terms'`

- [ ] **Step 7: Implémenter `scripts/ingest_hpo_terms.py`**

```python
"""Ingestion des détails de termes HPO par panel dans la couche raw."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import RAW
from ingestion.hpo import HP_TERMS_URL, fetch_hpo_term_details, parse_genes_to_phenotype
from ingestion.jsonl import dumps_gzipped
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    get_bytes,
    partition_uri,
    put_bytes,
)

OBJECT_NAME = "hpo_terms.jsonl.gz"
GENES_TO_PHENOTYPE_OBJECT = "genes_to_phenotype.txt"


def ingest_hpo_terms(
    logical_date: str, panel: str, genes: list[str], lake_uri: str | None = None
) -> str:
    """Dépose les détails des termes HPO du panel dans la couche raw.

    Les IDs viennent du fichier plat déposé par le DAG d'acquisition ; leur
    enrichissement dépend des gènes du panel, d'où le partitionnement `panel=`.
    """
    hpo_partition = partition_uri(RAW, "hpo", logical_date, lake_uri=lake_uri)
    flat = get_bytes(f"{hpo_partition}/{GENES_TO_PHENOTYPE_OBJECT}")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(flat)
        flat_path = Path(handle.name)
    try:
        rows = parse_genes_to_phenotype(flat_path, genes)
    finally:
        flat_path.unlink(missing_ok=True)

    details = fetch_hpo_term_details([row["hpo_id"] for row in rows])
    records = [
        {"hpo_id": hpo_id, "details": detail} for hpo_id, detail in details.items()
    ]

    partition = partition_uri(RAW, "hpo_terms", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="hpo_terms",
            logical_date=logical_date,
            source_url=HP_TERMS_URL,
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les détails de termes HPO dans la couche raw.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_hpo_terms(
        args.logical_date, args.panel, args.genes.split(","), lake_uri=args.lake_uri,
    ))
```

- [ ] **Step 8: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 113 passed, 1 deselected, en moins de 3 s

- [ ] **Step 9: Commit**

```bash
git add scripts/ingest_medgen.py scripts/ingest_hpo_terms.py tests/scripts/test_ingest_medgen.py tests/scripts/test_ingest_hpo_terms.py
git commit -m "feat: add per-panel MedGen and HPO term ingestion into the raw layer"
```

---

### Task 3 (A3): Stubs des quatre transformations

**Files:**
- Create: `src/transformations/__init__.py` (vide)
- Create: `src/transformations/raw_to_bronze.py`
- Create: `src/transformations/bronze_to_silver.py`
- Create: `src/transformations/silver_to_gold_rag.py`
- Create: `src/transformations/silver_to_gold_analytique.py`
- Test: `tests/transformations/__init__.py` (vide), `tests/transformations/test_stubs.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `transformations.raw_to_bronze.raw_to_bronze(logical_date: str, sources: list[str], panel: str | None = None, lake_uri: str | None = None) -> list[str]` — renverra les URI des partitions Bronze écrites.
  - `transformations.bronze_to_silver.bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None`
  - `transformations.silver_to_gold_rag.silver_to_gold_rag(logical_date: str, panel: str, lake_uri: str | None = None) -> None`
  - `transformations.silver_to_gold_analytique.silver_to_gold_analytique(logical_date: str, panel: str, lake_uri: str | None = None) -> None`

- [ ] **Step 1: Écrire les tests**

Créer `tests/transformations/test_stubs.py` :

```python
import pytest

from transformations.bronze_to_silver import bronze_to_silver
from transformations.raw_to_bronze import raw_to_bronze
from transformations.silver_to_gold_analytique import silver_to_gold_analytique
from transformations.silver_to_gold_rag import silver_to_gold_rag


def test_raw_to_bronze_names_sub_project_b():
    """Le message doit dire qui reprendra la tâche : un échec muet ou générique
    dans Airflow ne dirait pas où le pipeline s'arrête volontairement."""
    with pytest.raises(NotImplementedError, match="sous-projet B"):
        raw_to_bronze("2026-09-01", ["clinvar", "hpo"])


def test_bronze_to_silver_names_sub_project_c():
    with pytest.raises(NotImplementedError, match="sous-projet C"):
        bronze_to_silver("2026-09-01", "brca")


def test_silver_to_gold_rag_names_sub_project_d():
    with pytest.raises(NotImplementedError, match="sous-projet D"):
        silver_to_gold_rag("2026-09-01", "brca")


def test_silver_to_gold_analytique_names_sub_project_d():
    with pytest.raises(NotImplementedError, match="sous-projet D"):
        silver_to_gold_analytique("2026-09-01", "brca")
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'transformations'`

- [ ] **Step 3: Implémenter les stubs**

`src/transformations/raw_to_bronze.py` :

```python
from __future__ import annotations

SPEC = "docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md"


def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
    """Convertit les partitions raw des sources données en Parquet dans la couche bronze.

    Contrat d'entrée : partitions `raw/<source>/dt=<date>[/panel=<panel>]` complètes
    (marqueur `_SUCCESS` présent).

    Contrat de sortie : partitions `bronze/<source>/dt=<date>[/panel=<panel>]` en
    Parquet, closes par `manifest.json` puis `_SUCCESS`. Renvoie leurs URI.

    Règle : ce passage change le format et rien d'autre. Colonnes lues en chaînes,
    noms de colonnes normalisés, colonnes techniques `_source_version`,
    `_logical_date`, `_ingested_at`. Aucun filtre, aucun typage métier, aucun
    dédoublonnage ; seule une ligne entièrement vide peut être retirée. Le XML
    `conceptmeta` reste une chaîne. Le bulk ClinVar se lit en mode lazy et s'écrit en
    flux, jamais chargé entièrement en mémoire.
    """
    raise NotImplementedError(f"raw_to_bronze : implémenté par le sous-projet B ({SPEC}, §7)")
```

`src/transformations/bronze_to_silver.py` :

```python
from __future__ import annotations

from transformations.raw_to_bronze import SPEC


def bronze_to_silver(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit les tables Silver (Delta) du panel à partir du Bronze.

    Tables : clinvar_variant, clinvar_variant_gene, ncbi_gene, refseq_transcript,
    medgen_concept, medgen_mim, medgen_inheritance, hpo_gene_phenotype, hpo_term.
    Partition : `panel`. Une ligne par entité, aucun agrégat.

    Traitements : typage, filtre panel, filtre GRCh38, dédoublonnage sur `#AlleleID`,
    éclatement des lignes multi-gènes, parsing du XML MedGen, normalisation HGVS via
    le catalogue RefSeq, historisation SCD2 des reclassifications par `MERGE`.

    Interdits : filtrer sur la signification clinique (les variants bénins sont
    conservés) ; modifier la casse des HGVS, accessions et symboles de gènes.
    `RS# (dbSNP)` est un entier, `-1` quand absent.
    """
    raise NotImplementedError(f"bronze_to_silver : implémenté par le sous-projet C ({SPEC}, §7)")
```

`src/transformations/silver_to_gold_rag.py` :

```python
from __future__ import annotations

from transformations.raw_to_bronze import SPEC


def silver_to_gold_rag(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/rag/` (Delta) : un document par variant pour le RAG.

    Chaque document porte le contexte du gène, des maladies et des phénotypes, et ses
    références de citation (accession ClinVar, version, date de collecte).
    `chunk_id` est un hash déterministe du contenu, pour ne ré-embedder par `MERGE`
    que les documents modifiés. Lit le Silver, jamais `gold/analytique/`.
    """
    raise NotImplementedError(f"silver_to_gold_rag : implémenté par le sous-projet D ({SPEC}, §7)")
```

`src/transformations/silver_to_gold_analytique.py` :

```python
from __future__ import annotations

from transformations.raw_to_bronze import SPEC


def silver_to_gold_analytique(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/analytique/` (Delta) : modèle en étoile et agrégats.

    `fact_variant` et ses dimensions (gène, maladie, phénotype, signification
    clinique, temps) ; agrégats par gène, par signification et reclassifications
    par mois. Lu par DuckDB pour l'application. Lit le Silver, jamais `gold/rag/`.
    """
    raise NotImplementedError(
        f"silver_to_gold_analytique : implémenté par le sous-projet D ({SPEC}, §7)"
    )
```

- [ ] **Step 4: Vérifier qu'ils passent**

Run: `venv/bin/pytest tests/transformations -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Vérifier la suite complète et l'absence de moteur**

Run: `venv/bin/pytest -q && (grep -rnE "^(import|from) (polars|deltalake|pyspark|pandas)" src/transformations/ || echo "aucun moteur importe")`
Expected: `117 passed, 1 deselected`, puis `aucun moteur importe`

- [ ] **Step 6: Commit**

```bash
git add src/transformations/ tests/transformations/
git commit -m "feat: add documented stubs for the four medallion transformations"
```

---

### Task 4 (A4): Contrôle de complétude, panels et DAG d'acquisition

**Files:**
- Modify: `src/ingestion/storage.py` (ajout en fin de fichier)
- Test: `tests/ingestion/test_storage.py` (ajout)
- Modify: `requirements-dev.txt`
- Create: `dags/__init__.py`, `dags/common/__init__.py` (vides), `dags/common/panels.py`, `dags/dag_acquisition_sources.py`
- Test: `tests_airflow/__init__.py` (vide), `tests_airflow/conftest.py`, `tests_airflow/test_panels.py`, `tests_airflow/test_dag_acquisition.py`

**Interfaces:**
- Consumes: `ingestion.storage.partition_is_complete` ; `ingestion.config.BREAST_CANCER_GENES/SICKLE_CELL_GENES` ; `scripts.ingest_clinvar.ingest_clinvar` ; `scripts.ingest_hpo_files.ingest_hpo_files` ; `transformations.raw_to_bronze.raw_to_bronze` (Task A3).
- Produces:
  - `ingestion.storage.IncompletePartitionError(RuntimeError)`
  - `ingestion.storage.assert_partitions_complete(partitions: list[str], client=None) -> None`
  - `dags.common.panels.PANELS: dict[str, list[str]]`, `PANEL_LABELS: dict[str, str]`, `SHARED_SOURCES: list[str]`, `PANEL_SOURCES: list[str]`, `SOURCES_READY: Asset`
  - `dags.dag_acquisition_sources.dag`

**Pourquoi le contrôle vit dans `storage.py`.** Quatre tâches Airflow vérifient la complétude de partitions (`check_raw_shared`, `check_bronze_shared`, `check_raw`, `check_bronze`). La logique va dans `src/`, testable sans Airflow ; les DAGs n'appellent qu'une fonction.

- [ ] **Step 1: Écrire les tests du contrôle de complétude**

Ajouter à la fin de `tests/ingestion/test_storage.py` (ajouter `IncompletePartitionError` et `assert_partitions_complete` à l'import existant depuis `ingestion.storage`, en tête de fichier) :

```python
def _finalize(partition):
    finalize_partition(partition, build_manifest(
        source="s", logical_date="2026-09-01", source_url="u",
        source_version="v", files={}, record_count=0,
    ))


def test_assert_partitions_complete_accepts_finalized_partitions(tmp_path):
    first = f"file://{tmp_path}/raw/clinvar/dt=2026-09-01"
    second = f"file://{tmp_path}/raw/hpo/dt=2026-09-01"
    _finalize(first)
    _finalize(second)

    assert_partitions_complete([first, second])


def test_assert_partitions_complete_names_every_incomplete_partition(tmp_path):
    """Toutes les partitions incomplètes sont nommées en une fois : un message qui
    n'en citerait qu'une obligerait à relancer pour découvrir la suivante."""
    complete = f"file://{tmp_path}/raw/clinvar/dt=2026-09-01"
    missing_a = f"file://{tmp_path}/raw/hpo/dt=2026-09-01"
    missing_b = f"file://{tmp_path}/raw/medgen/dt=2026-09-01/panel=brca"
    _finalize(complete)

    with pytest.raises(IncompletePartitionError) as excinfo:
        assert_partitions_complete([complete, missing_a, missing_b])

    message = str(excinfo.value)
    assert missing_a in message
    assert missing_b in message
    assert complete not in message
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/ingestion/test_storage.py -q`
Expected: FAIL avec `ImportError: cannot import name 'IncompletePartitionError'`

- [ ] **Step 3: Implémenter le contrôle**

Ajouter à la fin de `src/ingestion/storage.py` :

```python
class IncompletePartitionError(RuntimeError):
    """Une ou plusieurs partitions n'ont pas de marqueur `_SUCCESS`."""


def assert_partitions_complete(partitions: list[str], client=None) -> None:
    """Lève si une partition est incomplète, en les nommant toutes.

    Utilisée par les tâches de contrôle des DAGs pour bloquer la propagation vers la
    couche suivante. Toutes les partitions sont vérifiées avant de lever.
    """
    incomplete = [p for p in partitions if not partition_is_complete(p, client=client)]
    if incomplete:
        raise IncompletePartitionError("partitions incomplètes : " + ", ".join(incomplete))
```

- [ ] **Step 4: Vérifier la passe rapide**

Run: `venv/bin/pytest -q`
Expected: PASS, 119 passed, 1 deselected, en moins de 3 s

- [ ] **Step 5: Installer Airflow pour les tests de DAG**

Ajouter la ligne `apache-airflow==3.3.1` à `requirements-dev.txt`, puis :

Run: `venv/bin/pip install -r requirements-dev.txt`
Expected: installation réussie. Compatibilité vérifiée au préalable : aucune erreur de résolution avec `requests==2.34.2`, `polars==1.44.1`, `boto3==1.41.5`, `pytest==9.1.1`, `responses==0.26.2`.

- [ ] **Step 6: Écrire les tests des panels et du DAG d'acquisition**

Créer `tests_airflow/__init__.py` (vide), puis `tests_airflow/conftest.py` :

```python
import os
import tempfile

# Airflow crée son répertoire de travail (airflow.cfg, logs) dès l'import. Sans
# cette ligne, les tests écriraient dans ~/airflow sur la machine du développeur.
# conftest.py est chargé avant les modules de test, donc avant tout import d'Airflow.
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-tests-"))
```

Puis `tests_airflow/test_panels.py` :

```python
from dags.common.panels import PANEL_SOURCES, PANELS, SHARED_SOURCES
from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES


def test_panels_reuse_the_tested_gene_lists_without_duplicating_them():
    """La liste de gènes a une seule source de vérité, déjà couverte par test_config.py."""
    assert PANELS["brca"] == BREAST_CANCER_GENES
    assert PANELS["sickle"] == SICKLE_CELL_GENES


def test_panels_cover_every_gene_of_the_project():
    covered = {gene for genes in PANELS.values() for gene in genes}
    assert len(covered) == 18


def test_sources_are_split_between_shared_and_panel_without_overlap():
    """Une source partagée convertie aussi par panel serait traitée deux fois ;
    une source oubliée ne serait jamais convertie."""
    assert set(SHARED_SOURCES) == {"clinvar", "hpo"}
    assert set(PANEL_SOURCES) == {"ncbi_gene", "refseq", "medgen", "hpo_terms"}
    assert not set(SHARED_SOURCES) & set(PANEL_SOURCES)
```

Créer `tests_airflow/test_dag_acquisition.py` :

```python
from dags.common.panels import SOURCES_READY
from dags.dag_acquisition_sources import dag


def test_acquisition_dag_runs_monthly_without_catchup():
    assert dag.schedule == "@monthly"
    assert dag.catchup is False


def test_acquisition_dag_has_the_expected_tasks():
    assert sorted(t.task_id for t in dag.tasks) == [
        "check_bronze_shared",
        "check_raw_shared",
        "download_clinvar_bulk",
        "download_hpo_files",
        "raw_to_bronze_shared",
    ]


def test_both_downloads_run_in_parallel_then_gate_on_check_raw():
    assert dag.get_task("download_clinvar_bulk").upstream_task_ids == set()
    assert dag.get_task("download_hpo_files").upstream_task_ids == set()
    assert dag.get_task("check_raw_shared").upstream_task_ids == {
        "download_clinvar_bulk",
        "download_hpo_files",
    }


def test_bronze_conversion_is_gated_on_both_sides():
    assert dag.get_task("raw_to_bronze_shared").upstream_task_ids == {"check_raw_shared"}
    assert dag.get_task("check_bronze_shared").upstream_task_ids == {"raw_to_bronze_shared"}


def test_the_asset_is_published_only_once_bronze_is_complete():
    """Les DAGs de panel lisent le bronze des sources partagées : les déclencher
    après check_raw les ferait démarrer avant que ce bronze existe."""
    assert SOURCES_READY in dag.get_task("check_bronze_shared").outlets
    assert SOURCES_READY not in dag.get_task("check_raw_shared").outlets
```

- [ ] **Step 7: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests_airflow -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'dags'`

- [ ] **Step 8: Implémenter `dags/common/panels.py`**

```python
from __future__ import annotations

from airflow.sdk import Asset

from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES

# Source unique de vérité : les listes de gènes vivent dans ingestion.config, où
# elles sont déjà sous test.
PANELS: dict[str, list[str]] = {
    "brca": BREAST_CANCER_GENES,
    "sickle": SICKLE_CELL_GENES,
}

PANEL_LABELS: dict[str, str] = {
    "brca": "Cancer du sein héréditaire",
    "sickle": "Drépanocytose et modificateurs HbF",
}

# Le bronze ne filtre pas sur le panel : la conversion d'une source partagée est
# identique pour tous les panels et s'exécute une seule fois, dans le DAG
# d'acquisition. Les sources par panel sont converties dans chaque DAG de panel.
SHARED_SOURCES: list[str] = ["clinvar", "hpo"]
PANEL_SOURCES: list[str] = ["ncbi_gene", "refseq", "medgen", "hpo_terms"]

# Publié quand le bronze des sources partagées est complet : les DAGs de panel se
# déclenchent sur la donnée réellement disponible, pas sur un horaire.
SOURCES_READY = Asset("s3://bronze/_sources_pretes")
```

- [ ] **Step 9: Implémenter `dags/dag_acquisition_sources.py`**

```python
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task

from dags.common.panels import SHARED_SOURCES, SOURCES_READY
from ingestion.storage import assert_partitions_complete
from scripts.ingest_clinvar import ingest_clinvar
from scripts.ingest_hpo_files import ingest_hpo_files
from transformations.raw_to_bronze import raw_to_bronze

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=2),
}

with DAG(
    dag_id="dag_acquisition_sources",
    description="Sources communes à tous les panels : dépôt raw puis conversion bronze",
    schedule="@monthly",
    start_date=dt.datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["raw", "bronze", "acquisition"],
) as dag:

    @task(task_id="download_clinvar_bulk")
    def download_clinvar_bulk(**context) -> str:
        return ingest_clinvar(context["ds"])

    @task(task_id="download_hpo_files")
    def download_hpo_files(**context) -> str:
        return ingest_hpo_files(context["ds"])

    @task(task_id="check_raw_shared")
    def check_raw_shared(clinvar_partition: str, hpo_partition: str) -> None:
        assert_partitions_complete([clinvar_partition, hpo_partition])

    @task(task_id="raw_to_bronze_shared")
    def raw_to_bronze_shared(**context) -> list[str]:
        return raw_to_bronze(context["ds"], SHARED_SOURCES)

    @task(task_id="check_bronze_shared", outlets=[SOURCES_READY])
    def check_bronze_shared(bronze_partitions: list[str]) -> None:
        assert_partitions_complete(bronze_partitions)

    checked_raw = check_raw_shared(download_clinvar_bulk(), download_hpo_files())
    bronze = raw_to_bronze_shared()
    checked_raw >> bronze
    check_bronze_shared(bronze)
```

- [ ] **Step 10: Vérifier les deux passes**

Run: `venv/bin/pytest tests_airflow -q && venv/bin/pytest -q`
Expected: `8 passed` pour `tests_airflow`, puis `119 passed, 1 deselected` en moins de 3 s pour la passe rapide — qui ne doit pas avoir ralenti, puisqu'elle n'importe pas Airflow.

- [ ] **Step 11: Commit**

```bash
git add src/ingestion/storage.py tests/ingestion/test_storage.py requirements-dev.txt dags/ tests_airflow/
git commit -m "feat: add partition checks, panels and the shared acquisition DAG"
```

---

### Task 5 (A5): DAGs par panel

**Files:**
- Create: `dags/dag_genomic_pipeline.py`
- Test: `tests_airflow/test_dag_genomic_pipeline.py`

**Interfaces:**
- Consumes: `dags.common.panels.PANELS/PANEL_LABELS/PANEL_SOURCES/SOURCES_READY` (Task A4) ; `ingestion.storage.assert_partitions_complete` (Task A4) ; `ingestion.errors.ConfigurationError` ; `scripts.ingest_ncbi_gene.build_client/ingest_ncbi_gene` ; `scripts.ingest_refseq.ingest_refseq` ; `scripts.ingest_medgen.ingest_medgen` et `scripts.ingest_hpo_terms.ingest_hpo_terms` (Task A2) ; les quatre transformations (Task A3).
- Produces: `dags.dag_genomic_pipeline.client_or_fail() -> NcbiClient` ; `dags.dag_genomic_pipeline.build_panel_dag(panel: str, genes: list[str]) -> DAG` ; `dag_genomic_pipeline_brca` et `dag_genomic_pipeline_sickle` au niveau du module.

- [ ] **Step 1: Écrire les tests**

Créer `tests_airflow/test_dag_genomic_pipeline.py` :

```python
import pytest

from dags.common.panels import SOURCES_READY
from dags.dag_genomic_pipeline import build_panel_dag

INGESTIONS = {"ingest_ncbi_gene", "ingest_refseq", "ingest_hpo_terms", "ingest_medgen"}


@pytest.fixture
def dag():
    return build_panel_dag("brca", ["BRCA1", "BRCA2"])


def test_panel_dag_is_triggered_by_the_shared_sources_asset(dag):
    assert dag.schedule == [SOURCES_READY]
    assert dag.catchup is False


def test_panel_dag_has_the_expected_tasks(dag):
    assert sorted(t.task_id for t in dag.tasks) == sorted(INGESTIONS | {
        "check_raw",
        "raw_to_bronze",
        "check_bronze",
        "bronze_to_silver",
        "quality_check_silver",
        "silver_to_gold_rag",
        "silver_to_gold_analytique",
    })


def test_the_four_ingestions_run_in_parallel(dag):
    """MedGen dépend du bulk ClinVar brut, mais celui-ci est déposé par le DAG
    d'acquisition, qui a terminé avant de publier l'Asset."""
    for task_id in INGESTIONS:
        assert dag.get_task(task_id).upstream_task_ids == set()


def test_check_raw_waits_for_all_four_ingestions(dag):
    assert dag.get_task("check_raw").upstream_task_ids == INGESTIONS


def test_the_layers_are_strictly_sequential(dag):
    assert dag.get_task("raw_to_bronze").upstream_task_ids == {"check_raw"}
    assert dag.get_task("check_bronze").upstream_task_ids == {"raw_to_bronze"}
    assert dag.get_task("bronze_to_silver").upstream_task_ids == {"check_bronze"}
    assert dag.get_task("quality_check_silver").upstream_task_ids == {"bronze_to_silver"}


def test_the_two_gold_outputs_read_silver_not_each_other(dag):
    assert dag.get_task("silver_to_gold_rag").upstream_task_ids == {"quality_check_silver"}
    assert dag.get_task("silver_to_gold_analytique").upstream_task_ids == {"quality_check_silver"}


def test_transient_failures_are_retried(dag):
    assert dag.get_task("ingest_ncbi_gene").retries == 3


def test_configuration_errors_fail_without_consuming_retries(monkeypatch):
    """Une configuration manquante est permanente : AirflowFailException échoue la
    tâche immédiatement, sans passer par les trois retries."""
    from airflow.sdk.exceptions import AirflowFailException

    from dags import dag_genomic_pipeline
    from ingestion.errors import ConfigurationError

    def refuser():
        raise ConfigurationError("NCBI_EMAIL manquant")

    monkeypatch.setattr(dag_genomic_pipeline, "build_client", refuser)

    with pytest.raises(AirflowFailException, match="NCBI_EMAIL"):
        dag_genomic_pipeline.client_or_fail()


def test_both_panel_dags_are_exposed_at_module_level():
    from dags import dag_genomic_pipeline

    assert dag_genomic_pipeline.dag_genomic_pipeline_brca.dag_id == "dag_genomic_pipeline_brca"
    assert dag_genomic_pipeline.dag_genomic_pipeline_sickle.dag_id == "dag_genomic_pipeline_sickle"
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests_airflow/test_dag_genomic_pipeline.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'dags.dag_genomic_pipeline'`

- [ ] **Step 3: Implémenter `dags/dag_genomic_pipeline.py`**

```python
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from dags.common.panels import PANEL_LABELS, PANEL_SOURCES, PANELS, SOURCES_READY
from ingestion.errors import ConfigurationError
from ingestion.http_client import NcbiClient
from ingestion.storage import assert_partitions_complete
from scripts.ingest_hpo_terms import ingest_hpo_terms
from scripts.ingest_medgen import ingest_medgen
from scripts.ingest_ncbi_gene import build_client, ingest_ncbi_gene
from scripts.ingest_refseq import ingest_refseq
from transformations.bronze_to_silver import bronze_to_silver
from transformations.raw_to_bronze import SPEC, raw_to_bronze
from transformations.silver_to_gold_analytique import silver_to_gold_analytique
from transformations.silver_to_gold_rag import silver_to_gold_rag

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=3),
}


def client_or_fail() -> NcbiClient:
    """Construit le client NCBI, ou échoue définitivement.

    Une configuration manquante ne se résout pas en réessayant : `AirflowFailException`
    marque la tâche en échec sans consommer les retries.
    """
    try:
        return build_client()
    except ConfigurationError as exc:
        raise AirflowFailException(str(exc)) from exc


def build_panel_dag(panel: str, genes: list[str]) -> DAG:
    """Construit le DAG médaillon d'un panel de gènes, déclenché par l'Asset
    publié quand le bronze des sources partagées est complet."""
    with DAG(
        dag_id=f"dag_genomic_pipeline_{panel}",
        description=f"Pipeline médaillon — {PANEL_LABELS.get(panel, panel)}",
        schedule=[SOURCES_READY],
        start_date=dt.datetime(2026, 1, 1),
        catchup=False,
        default_args=DEFAULT_ARGS,
        tags=["medaillon", panel],
    ) as dag:

        @task(task_id="ingest_ncbi_gene")
        def task_ncbi_gene(**context) -> str:
            return ingest_ncbi_gene(context["ds"], panel, genes, client_or_fail())

        @task(task_id="ingest_refseq")
        def task_refseq(**context) -> str:
            return ingest_refseq(context["ds"], panel, genes, client_or_fail())

        @task(task_id="ingest_hpo_terms")
        def task_hpo_terms(**context) -> str:
            return ingest_hpo_terms(context["ds"], panel, genes)

        @task(task_id="ingest_medgen")
        def task_medgen(**context) -> str:
            return ingest_medgen(context["ds"], panel, genes, client_or_fail())

        @task(task_id="check_raw")
        def task_check_raw(
            ncbi_gene_partition: str,
            refseq_partition: str,
            hpo_terms_partition: str,
            medgen_partition: str,
        ) -> None:
            assert_partitions_complete([
                ncbi_gene_partition,
                refseq_partition,
                hpo_terms_partition,
                medgen_partition,
            ])

        @task(task_id="raw_to_bronze")
        def task_raw_to_bronze(**context) -> list[str]:
            return raw_to_bronze(context["ds"], PANEL_SOURCES, panel=panel)

        @task(task_id="check_bronze")
        def task_check_bronze(bronze_partitions: list[str]) -> None:
            assert_partitions_complete(bronze_partitions)

        @task(task_id="bronze_to_silver")
        def task_bronze_to_silver(**context) -> None:
            bronze_to_silver(context["ds"], panel)

        @task(task_id="quality_check_silver")
        def task_quality_check_silver(**context) -> None:
            raise NotImplementedError(
                f"quality_check_silver : implémenté par le sous-projet C ({SPEC}, §7)"
            )

        @task(task_id="silver_to_gold_rag")
        def task_silver_to_gold_rag(**context) -> None:
            silver_to_gold_rag(context["ds"], panel)

        @task(task_id="silver_to_gold_analytique")
        def task_silver_to_gold_analytique(**context) -> None:
            silver_to_gold_analytique(context["ds"], panel)

        checked_raw = task_check_raw(
            task_ncbi_gene(), task_refseq(), task_hpo_terms(), task_medgen()
        )
        bronze = task_raw_to_bronze()
        checked_raw >> bronze
        checked_bronze = task_check_bronze(bronze)
        silver = task_bronze_to_silver()
        quality = task_quality_check_silver()
        checked_bronze >> silver >> quality >> [
            task_silver_to_gold_rag(),
            task_silver_to_gold_analytique(),
        ]

    return dag


dag_genomic_pipeline_brca = build_panel_dag("brca", PANELS["brca"])
dag_genomic_pipeline_sickle = build_panel_dag("sickle", PANELS["sickle"])
```

- [ ] **Step 4: Vérifier qu'ils passent**

Run: `venv/bin/pytest tests_airflow/test_dag_genomic_pipeline.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Vérifier les deux passes**

Run: `venv/bin/pytest tests_airflow -q && venv/bin/pytest -q`
Expected: `17 passed` pour `tests_airflow`, puis `119 passed, 1 deselected` en moins de 3 s

- [ ] **Step 6: Commit**

```bash
git add dags/dag_genomic_pipeline.py tests_airflow/test_dag_genomic_pipeline.py
git commit -m "feat: add per-panel four-layer DAGs triggered by the sources Asset"
```

---

### Task 6 (A6): Stack Docker et documentation

**Files:**
- Create: `docker/airflow/Dockerfile`, `docker/minio/create-buckets.sh`, `docker-compose.yml`, `.env.docker.example`
- Modify: `.gitignore`, `README.md`, `CLAUDE.md`, `nifi/README.md`

**Interfaces:**
- Consumes: `requirements.txt`, `dags/`, `src/`, `scripts/`.
- Produces: une stack lancée par `docker compose --env-file .env.docker up -d --build`, quatre buckets créés, Airflow sur `http://localhost:8080`, console MinIO sur `http://localhost:${MINIO_CONSOLE_PORT}` (9001 par défaut).

**Trois défauts de l'ancien plan corrigés ici, vérifiés sur Airflow 3.3.1 :**

1. **Les dépendances allaient dans un venv que personne n'utilisait.** Les tâches TaskFlow s'exécutent dans l'interpréteur d'Airflow, et le `dag-processor` importe les fichiers de DAG, donc `scripts/` puis `ingestion/` puis `polars`. Les dépendances doivent être installées dans l'environnement d'Airflow. La compatibilité a été vérifiée (résolution sans conflit) ; épingler `apache-airflow==3.3.1` dans la même commande `pip` empêche toute modification d'Airflow.
2. **`airflow users create` n'existe pas en Airflow 3.3.1.** Le gestionnaire d'authentification par défaut est `SimpleAuthManager`, sans cette commande. Le `|| true` de l'ancien plan masquait l'échec : aucun compte n'aurait été créé. Les utilisateurs se déclarent par `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS`, et le mot de passe est généré dans `simple_auth_manager_passwords.json.generated`.
3. **Les tâches n'auraient jamais pu s'exécuter.** Sans configuration, `execution_api_server_url` vaut `http://localhost:8080/execution/`, qui ne désigne pas l'api-server depuis le conteneur du scheduler. Et `jwt_secret` est généré différemment dans chaque `AIRFLOW_HOME`, donc dans chaque conteneur (mesuré : deux homes, deux secrets). Les deux sont fixés et partagés.

- [ ] **Step 1: Écrire le Dockerfile**

`docker/airflow/Dockerfile` :

```dockerfile
FROM apache/airflow:3.3.1-python3.12

# Les tâches TaskFlow et le dag-processor exécutent le code du projet dans
# l'interpréteur d'Airflow : les dépendances doivent y être installées. Épingler
# apache-airflow dans la même commande empêche pip de modifier Airflow.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir "apache-airflow==3.3.1" -r /tmp/requirements.txt
```

- [ ] **Step 2: Écrire le script des buckets**

`docker/minio/create-buckets.sh` :

```bash
#!/bin/sh
set -e

# Une couche du médaillon = un bucket. Idempotent : relancer la stack ne casse rien.
mc alias set local "http://minio:9000" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
for bucket in raw bronze silver gold; do
  mc mb --ignore-existing "local/${bucket}"
  echo "bucket ${bucket} pret"
done
```

- [ ] **Step 3: Écrire le docker-compose**

`docker-compose.yml` :

```yaml
x-airflow-common: &airflow-common
  build:
    context: .
    dockerfile: docker/airflow/Dockerfile
  environment:
    AIRFLOW__CORE__EXECUTOR: LocalExecutor
    AIRFLOW__CORE__LOAD_EXAMPLES: "false"
    AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:${POSTGRES_PASSWORD}@postgres:5432/airflow
    AIRFLOW__CORE__DAGS_FOLDER: /opt/projet/dags
    # Les tâches joignent l'API d'exécution de l'api-server : localhost désignerait
    # le conteneur du scheduler lui-même.
    AIRFLOW__CORE__EXECUTION_API_SERVER_URL: http://airflow-apiserver:8080/execution/
    # Partagé entre composants : sinon chaque conteneur génère le sien.
    AIRFLOW__API_AUTH__JWT_SECRET: ${AIRFLOW_JWT_SECRET}
    AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS: admin:admin
    PYTHONPATH: /opt/projet:/opt/projet/src
    LAKE_URI: "s3://"
    AWS_ENDPOINT_URL: "http://minio:9000"
    AWS_ACCESS_KEY_ID: ${MINIO_ROOT_USER}
    AWS_SECRET_ACCESS_KEY: ${MINIO_ROOT_PASSWORD}
    AWS_REGION: us-east-1
    NCBI_EMAIL: ${NCBI_EMAIL}
    NCBI_API_KEY: ${NCBI_API_KEY:-}
  volumes:
    - .:/opt/projet
  working_dir: /opt/projet
  depends_on:
    postgres:
      condition: service_healthy
    minio:
      condition: service_healthy

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: airflow
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U airflow"]
      interval: 10s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1g

  minio:
    image: quay.io/minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    ports:
      # Ports hôte configurables : sur une machine de développement, 9000 et 9001
      # sont souvent déjà pris (Portainer, un autre MinIO). Les services Airflow
      # joignent MinIO par le réseau Docker (minio:9000), pas par ces ports.
      - "${MINIO_API_PORT:-9000}:9000"
      - "${MINIO_CONSOLE_PORT:-9001}:9001"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 1g

  minio-init:
    image: quay.io/minio/mc
    depends_on:
      minio:
        condition: service_healthy
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    entrypoint: ["/bin/sh", "/scripts/create-buckets.sh"]
    volumes:
      - ./docker/minio/create-buckets.sh:/scripts/create-buckets.sh:ro

  airflow-init:
    <<: *airflow-common
    command: ["db", "migrate"]
    restart: "no"

  airflow-apiserver:
    <<: *airflow-common
    command: api-server
    ports:
      - "8080:8080"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1536m

  airflow-scheduler:
    <<: *airflow-common
    command: scheduler
    restart: unless-stopped
    deploy:
      resources:
        limits:
          # Avec LocalExecutor, les tâches s'exécutent dans ce conteneur.
          memory: 2g

  airflow-dag-processor:
    <<: *airflow-common
    command: dag-processor
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1g

  airflow-triggerer:
    <<: *airflow-common
    command: triggerer
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 768m

volumes:
  postgres-data:
  minio-data:
```

- [ ] **Step 4: Écrire le modèle d'environnement**

`.env.docker.example` :

```
# Modèle. Copier en .env.docker et y saisir de vraies valeurs (fichier gitignoré).
POSTGRES_PASSWORD=
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=

# Ports hôte de MinIO. Changer si 9000/9001 sont déjà occupés (ex. 9010 et 9011).
MINIO_API_PORT=9000
MINIO_CONSOLE_PORT=9001

# Secret partagé entre composants Airflow. Générer avec :
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
AIRFLOW_JWT_SECRET=

# Obligatoire (politique NCBI E-utilities).
NCBI_EMAIL=
# Recommandée : 10 req/s au lieu de 3. Laisser VIDE si absente — une valeur
# factice ferait passer le limiteur en cadence rapide et provoquerait des erreurs.
NCBI_API_KEY=
```

Ajouter `.env.docker` à `.gitignore`, sous la ligne `.env`.

- [ ] **Step 5: Construire et démarrer la stack**

```bash
cp .env.docker.example .env.docker   # puis renseigner les valeurs
docker compose --env-file .env.docker up -d --build
docker compose --env-file .env.docker ps -a
```
Expected: `postgres`, `minio`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`, `airflow-triggerer` en état `running` ; `minio-init` et `airflow-init` sortis en code 0.

- [ ] **Step 6: Vérifier les buckets, les DAGs et la connexion**

```bash
docker compose --env-file .env.docker logs minio-init | grep "pret"
docker compose --env-file .env.docker exec airflow-scheduler airflow dags list-import-errors
docker compose --env-file .env.docker exec airflow-scheduler airflow dags list
docker compose --env-file .env.docker exec airflow-apiserver cat /opt/airflow/simple_auth_manager_passwords.json.generated
```
Expected: quatre lignes `bucket raw pret`, `bucket bronze pret`, `bucket silver pret`, `bucket gold pret` ; aucune erreur d'import ; les DAGs `dag_acquisition_sources`, `dag_genomic_pipeline_brca`, `dag_genomic_pipeline_sickle` listés ; un JSON `{"admin": "<mot de passe>"}` permettant la connexion sur `http://localhost:8080`.

- [ ] **Step 7: Vérifier que les tâches s'exécutent réellement**

Ce contrôle prouve que l'API d'exécution et le secret JWT sont correctement configurés — c'est le défaut n°3 de l'ancien plan. Il déclenche un vrai téléchargement ClinVar (442 Mo) et appelle GitHub, mais aucune API NCBI.

```bash
docker compose --env-file .env.docker exec airflow-scheduler airflow dags trigger dag_acquisition_sources
```

Attendre la fin du run, puis, dans l'interface ou via `airflow tasks states-for-dag-run` :

Expected: `download_clinvar_bulk`, `download_hpo_files` et `check_raw_shared` en `success` ; `raw_to_bronze_shared` en `failed` avec le message `raw_to_bronze : implémenté par le sous-projet B` ; `check_bronze_shared` en `upstream_failed`. Dans la console MinIO, les partitions `raw/clinvar/dt=…/` et `raw/hpo/dt=…/` contiennent leurs données, `manifest.json` et `_SUCCESS`.

Un `failed` sur `download_clinvar_bulk` avec une erreur d'authentification ou de connexion à l'API d'exécution signifie que les variables `AIRFLOW__CORE__EXECUTION_API_SERVER_URL` ou `AIRFLOW__API_AUTH__JWT_SECRET` ne sont pas prises en compte.

- [ ] **Step 8: Vérifier l'empreinte mémoire**

```bash
docker stats --no-stream --format '{{.Name}}: {{.MemUsage}}'
```
Expected: total au repos inférieur à 7,25 Go, la marge prévue pour les tâches sur le VPS de 12 Go.

- [ ] **Step 9: Documenter dans le README**

Ajouter à `README.md`, après la section « Tests », une section « Lancer le pipeline médaillon » qui contient :

- les deux passes de tests : `venv/bin/pytest -q` (logique, sans infrastructure) et `venv/bin/pytest tests_airflow -q` (structure des DAGs, nécessite `apache-airflow`) ;
- la copie de `.env.docker.example`, la génération de `AIRFLOW_JWT_SECRET`, et `docker compose --env-file .env.docker up -d --build` ;
- l'accès à Airflow sur `http://localhost:8080` (mot de passe dans `/opt/airflow/simple_auth_manager_passwords.json.generated` du conteneur `airflow-apiserver`) et à la console MinIO sur `http://localhost:<MINIO_CONSOLE_PORT>` (9001 par défaut) ;
- l'état volontaire du pipeline : les passages `raw_to_bronze`, `bronze_to_silver`, `quality_check_silver`, `silver_to_gold_rag` et `silver_to_gold_analytique` échouent explicitement en nommant le sous-projet qui les implémentera. Conséquence : tant que le sous-projet B n'est pas livré, `check_bronze_shared` ne réussit pas, l'Asset n'est pas publié, et les DAGs de panel ne se déclenchent pas automatiquement. Pour exercer l'ingestion par panel, les déclencher à la main (`airflow dags trigger dag_genomic_pipeline_brca`) : les quatre ingestions et `check_raw` s'exécutent, puis le run s'arrête à `raw_to_bronze`.

- [ ] **Step 10: Mettre à jour `CLAUDE.md` et `nifi/README.md`**

Dans `CLAUDE.md`, remplacer le titre `## Orchestration (NiFi) — scoped to stage 1 only` et tout son contenu par :

```markdown
## Orchestration — Airflow 3 (NiFi : alternative évaluée, écartée)

**NiFi est retiré du chemin d'implémentation.** Le dossier `nifi/` est conservé comme
alternative implémentée, mesurée et écartée : ses apports ici (déclenchement planifié,
routage succès/échec, journalisation) sont un sous-ensemble strict de ceux d'Airflow,
pour un coût mesuré de 1,37 Gio de RAM au repos. Chiffres : `docs/choix_contexte.md`.

**Architecture en quatre couches** (spec : `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md`) :
`raw` (format de la source) → `bronze` (Parquet) → `silver` (Delta) → `gold/rag` et
`gold/analytique` (Delta), chacune dans un bucket MinIO. Moteur : Polars.

- `scripts/ingest_*.py` écrivent uniquement en `raw`.
- `src/transformations/` contient les passages entre couches (stubs tant que les
  sous-projets B, C et D ne sont pas livrés).
- `dags/` : un DAG d'acquisition mensuel pour les sources partagées, un DAG par panel.
- `docker/` et `docker-compose.yml` : Airflow 3, PostgreSQL, MinIO.

**Règle non négociable :** la logique métier vit dans `src/` et `scripts/`, testée sans
infrastructure ; Airflow ne fait qu'appeler des fonctions ; MinIO ne fait que stocker.

**Deux passes de tests :** `pytest -q` (logique, moins de 3 s, sans réseau ni conteneur)
et `pytest tests_airflow -q` (structure des DAGs ; séparée parce que `import airflow.sdk`
prend à lui seul ~3 s).
```

Ajouter en tête de `nifi/README.md`, juste après le titre :

```markdown
> ⚠️ **Alternative écartée.** Ce dossier n'est plus le chemin d'orchestration du projet.
> Il est conservé pour documenter un choix évalué puis écarté avec mesures — voir
> `CLAUDE.md`. L'orchestration active vit dans `dags/`.
```

- [ ] **Step 11: Commit**

```bash
git add docker-compose.yml docker/ .env.docker.example .gitignore README.md CLAUDE.md nifi/README.md
git commit -m "feat: add the Airflow 3 + MinIO stack with four medallion buckets"
```

---

## Vérification finale

- [ ] **Passe rapide**

Run: `venv/bin/pytest -q`
Expected: `119 passed, 1 deselected`, en moins de 3 s, sans réseau ni conteneur

- [ ] **Passe Airflow**

Run: `venv/bin/pytest tests_airflow -q`
Expected: `17 passed`

- [ ] **Aucune ingestion hors de `raw`**

Run: `grep -rn "BRONZE" scripts/ || echo "aucun script n'ecrit hors de raw"`
Expected: `aucun script n'ecrit hors de raw`

- [ ] **Aucun moteur importé directement par les stubs ou les DAGs**

Run: `grep -rnE "^(import|from) (polars|deltalake|pyspark|pandas)" src/transformations/ dags/ || echo "aucun moteur importe"`
Expected: `aucun moteur importe`

- [ ] **Chemin autonome intact**

Run: `venv/bin/python -c "import sys; sys.path.insert(0,'src'); from ingestion.orchestrate import build_gene_documents; print('ok')"`
Expected: `ok`
