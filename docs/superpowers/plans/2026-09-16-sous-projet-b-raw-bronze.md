# Sous-projet B — `raw → bronze` en Polars — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter `raw_to_bronze()` (actuellement un stub `NotImplementedError`) : convertir les six sources raw du pipeline (`clinvar`, `hpo`, `ncbi_gene`, `refseq`, `medgen`, `hpo_terms`) en partitions Parquet dans la couche bronze.

**Architecture :** Deux convertisseurs génériques — `_convert_flat_source` pour les deux sources TSV (`clinvar` en lazy/flux, `hpo`), `_convert_jsonl_source` pour les quatre sources JSONL (payload imbriqué sérialisé en chaîne JSON, jamais aplati) — dispatchés par une petite table déclarative par source. `raw_to_bronze()` boucle sur `sources`, écrit chaque partition bronze selon le protocole `begin_partition` → données → manifest → `_SUCCESS` déjà utilisé par la couche raw.

**Tech Stack :** Python 3.12, Polars 1.44.1, pytest 9.1.1.

**Spec :** `docs/superpowers/specs/2026-09-16-sous-projet-b-raw-bronze-design.md` (amende/précise `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md`, §3.2 et §7, qui reste valable pour tout ce qu'elle ne remplace pas).

## Global Constraints

- Signature figée, ne pas modifier : `raw_to_bronze(logical_date: str, sources: list[str], panel: str | None = None, lake_uri: str | None = None) -> list[str]`.
- Colonnes lues en chaînes de caractères (`Utf8`) partout. Aucun filtre, aucun typage métier, aucun dédoublonnage. Seule une ligne entièrement vide peut être retirée ; une ligne incomplète est conservée.
- Les payloads imbriqués (`esummary`, `transcripts`, `details`) restent des chaînes JSON (`<champ>_json`), jamais aplatis en colonnes individuelles.
- Normalisation des noms de colonnes : mécanique, aucune exception. `re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()`. `#AlleleID` → `alleleid`, pas `allele_id` (pas de coupure aux frontières minuscule→MAJUSCULE — voir spec §3.2 pour la justification).
- Le bulk ClinVar (442 Mo compressés, ~6M lignes) se lit en lazy (`pl.scan_csv` + `sink_parquet`), jamais chargé entièrement en mémoire. Téléchargé en local d'abord (`open_stream`), jamais scanné directement depuis `s3://`.
- Un seul fichier de sortie par partition bronze : `data.parquet`.
- Colonnes techniques `_source_version`/`_logical_date`/`_ingested_at` lues depuis le manifest de la partition **raw** correspondante (`source_version`, et non recalculées — voir spec §3.5), jamais depuis la partition bronze elle-même.
- Manifest bronze : `source_url` = URI de la partition raw d'origine (traçabilité raw→bronze, pas l'URL externe).
- Ne jamais importer `deltalake`, `pyspark` ni `pandas`. Seul Polars est le moteur.
- Commentaires, docstrings et messages en français. Imports en tête de fichier (E402).
- Deux passes de tests : `venv/bin/pytest -q` (moins de 3 s, sans réseau ni conteneur — ce sous-projet y reste entièrement) et `venv/bin/pytest tests_airflow -q` (inchangée par ce plan, à revérifier seulement en étape finale).

---

## Structure des fichiers

**Modifié :** `src/transformations/raw_to_bronze.py` (remplace le stub), `tests/transformations/test_stubs.py` (retire le test devenu caduc).

**Créé :** `tests/transformations/test_raw_to_bronze.py`.

---

### Task 1: Retirer le test du stub, fonction de normalisation des noms de colonnes

**Files:**
- Modify: `tests/transformations/test_stubs.py`
- Create: `tests/transformations/test_raw_to_bronze.py`
- Modify: `src/transformations/raw_to_bronze.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `transformations.raw_to_bronze._normalize_column_name(name: str) -> str`.

**Pourquoi retirer le test en premier.** `test_raw_to_bronze_names_sub_project_b` attend un `NotImplementedError` : dès que `raw_to_bronze` fait un vrai travail, ce test échoue pour une mauvaise raison (plus de stub, pas un bug). Il doit partir avant toute implémentation, pas après.

- [ ] **Step 1: Retirer le test caduc**

Dans `tests/transformations/test_stubs.py`, retirer entièrement la fonction `test_raw_to_bronze_names_sub_project_b` et son import devenu inutile :

```python
from transformations.raw_to_bronze import raw_to_bronze
```

Le fichier ne doit garder que les imports et tests de `bronze_to_silver`, `silver_to_gold_rag`, `silver_to_gold_analytique`.

- [ ] **Step 2: Vérifier que la suite passe toujours (le stub raw_to_bronze existe encore)**

Run: `venv/bin/pytest tests/transformations -q`
Expected: PASS, 3 passed (les trois tests de stubs restants)

- [ ] **Step 3: Écrire les tests de normalisation des noms de colonnes (ils doivent échouer)**

Créer `tests/transformations/test_raw_to_bronze.py` :

```python
from transformations.raw_to_bronze import _normalize_column_name


def test_normalize_column_name_lowercases_a_plain_word():
    assert _normalize_column_name("Assembly") == "assembly"


def test_normalize_column_name_has_no_word_boundary_without_a_separator():
    """Pas de coupure aux frontières minuscule->MAJUSCULE : aucun indice mécanique
    pour deviner où découper un nom sans séparateur d'origine."""
    assert _normalize_column_name("#AlleleID") == "alleleid"
    assert _normalize_column_name("GeneSymbol") == "genesymbol"


def test_normalize_column_name_collapses_separators_to_one_underscore():
    assert _normalize_column_name("RS# (dbSNP)") == "rs_dbsnp"
    assert _normalize_column_name("nsv/esv (dbVar)") == "nsv_esv_dbvar"


def test_normalize_column_name_keeps_an_existing_single_underscore():
    assert _normalize_column_name("HGVS_p") == "hgvs_p"
```

- [ ] **Step 4: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: FAIL avec `ImportError: cannot import name '_normalize_column_name'`

- [ ] **Step 5: Implémenter `_normalize_column_name`**

Remplacer entièrement le contenu de `src/transformations/raw_to_bronze.py` par :

```python
"""Passage raw -> bronze : conversion en Parquet, colonnes techniques, rien d'autre.

Deux convertisseurs génériques (`_convert_flat_source` pour les sources TSV,
`_convert_jsonl_source` pour les sources JSONL) dispatchés par une table déclarative
par source. Voir docs/superpowers/specs/2026-09-16-sous-projet-b-raw-bronze-design.md.
"""

from __future__ import annotations

import re


def _normalize_column_name(name: str) -> str:
    """Minuscule, tout non-alphanumérique devient `_`, runs fusionnés, bords retirés.

    Mécanique et sans exception : `#AlleleID` -> `alleleid` (pas de coupure aux
    frontières minuscule->MAJUSCULE, qui serait incohérente avec un sigle comme
    `dbSNP` dans `RS# (dbSNP)` -> `rs_dbsnp`, laissé tel quel). Le découpage en mots
    est une décision Silver, pas Bronze.
    """
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
    """Convertit les partitions raw des sources données en Parquet dans la couche bronze.

    Contrat d'entrée : partitions `raw/<source>/dt=<date>[/panel=<panel>]` complètes
    (marqueur `_SUCCESS` présent, vérifié par `check_raw` en amont — pas revérifié ici).

    Contrat de sortie : partitions `bronze/<source>/dt=<date>[/panel=<panel>]` en
    Parquet (`data.parquet`), écrites selon le protocole `begin_partition` → données →
    manifest → `_SUCCESS`. Renvoie leurs URI.

    Règle : ce passage change le format et rien d'autre. Colonnes lues en chaînes,
    noms de colonnes normalisés (sources flat), colonnes techniques
    `_source_version`/`_logical_date`/`_ingested_at` propagées depuis le manifest
    raw. Aucun filtre, aucun typage métier, aucun dédoublonnage ; seule une ligne
    entièrement vide peut être retirée. Les payloads imbriqués des sources JSONL
    restent des chaînes JSON, jamais aplatis. Le bulk ClinVar se lit en mode lazy et
    s'écrit en flux, jamais chargé entièrement en mémoire.
    """
    raise NotImplementedError("raw_to_bronze : implémenté tâche par tâche — voir Task 4")
```

- [ ] **Step 6: Vérifier que les tests de normalisation passent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: PASS, 4 passed

- [ ] **Step 7: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, 155 passed, 1 deselected (158 moins les 3 tests de stub retirés... en fait le compte exact dépend de l'état courant : vérifier qu'aucun test ne casse, peu importe le total affiché)

- [ ] **Step 8: Commit**

```bash
git add tests/transformations/test_stubs.py tests/transformations/test_raw_to_bronze.py src/transformations/raw_to_bronze.py
git commit -m "refactor: remove the raw_to_bronze stub test, add column-name normalisation"
```

---

### Task 2: `_convert_flat_source` (clinvar, hpo)

**Files:**
- Modify: `src/transformations/raw_to_bronze.py`
- Test: `tests/transformations/test_raw_to_bronze.py`

**Interfaces:**
- Consumes: `ingestion.storage.open_stream`.
- Produces: `transformations.raw_to_bronze._convert_flat_source(raw_partition: str, object_name: str, technical_columns: dict[str, str], work_dir: Path) -> Path` — renvoie le chemin local du Parquet écrit.

**Vérifié à la main avant d'écrire ce plan** (sanity check Polars 1.44.1, voir session) : `pl.scan_csv(path, separator="\t", infer_schema_length=0)` lit tout en `Utf8` ; `.collect_schema().names()` donne les noms de colonnes sans charger les données ; `~pl.all_horizontal(pl.all().is_null())` filtre correctement une ligne entièrement vide (confirmé sur un fixture à 3 lignes, la ligne vide disparaît, les deux autres restent) ; `lf.sink_parquet(path)` écrit en flux.

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_raw_to_bronze.py` :

```python
import polars as pl

from ingestion.storage import put_bytes
from transformations.raw_to_bronze import _convert_flat_source

FLAT_TSV = (
    "#AlleleID\tGeneSymbol\tAssembly\n"
    "1\tBRCA1\tGRCh38\n"
    "\t\t\n"
    "2\tHBB\t\n"
)


FLAT_OBJECT = "variant_summary.txt.gz"


def _seed_flat_object(tmp_path, object_name=FLAT_OBJECT):
    import gzip

    partition = f"file://{tmp_path}/lake/raw/clinvar/dt=2026-09-01"
    put_bytes(f"{partition}/{object_name}", gzip.compress(FLAT_TSV.encode()))
    return partition


def test_convert_flat_source_normalizes_column_names_and_adds_technical_columns(tmp_path):
    partition = _seed_flat_object(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_flat_source(
        partition,
        FLAT_OBJECT,
        {"_source_version": "2026-09", "_logical_date": "2026-09-01", "_ingested_at": "2026-09-01T00:00:00+00:00"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df.columns == [
        "alleleid", "genesymbol", "assembly",
        "_source_version", "_logical_date", "_ingested_at",
    ]
    assert df.schema["alleleid"] == pl.Utf8


def test_convert_flat_source_drops_the_entirely_empty_row_keeps_the_incomplete_one(tmp_path):
    partition = _seed_flat_object(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_flat_source(
        partition, FLAT_OBJECT,
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df["alleleid"].to_list() == ["1", "2"]
    # ligne incomplète (Assembly vide pour HBB) conservée, pas de filtre par colonne
    assert df.filter(pl.col("genesymbol") == "HBB")["assembly"].to_list() == [None]


def test_convert_flat_source_streams_via_open_stream(tmp_path):
    """Garde de streaming : le fichier passe par open_stream (flux), jamais chargé
    d'un bloc. Un fixture de quelques lignes ne prouve pas la tenue mémoire sur les
    6M lignes réelles du bulk ClinVar — seule l'inspection du chemin de code
    l'atteste, comme pour ingest_medgen.py (test_ingest_medgen_streams_the_bulk)."""
    from unittest.mock import patch

    from ingestion.storage import open_stream

    partition = _seed_flat_object(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    with patch("transformations.raw_to_bronze.open_stream", wraps=open_stream) as espion:
        _convert_flat_source(
            partition, FLAT_OBJECT,
            {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
            work_dir,
        )

    assert espion.call_count == 1
    assert espion.call_args.args[0] == f"{partition}/{FLAT_OBJECT}"
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: FAIL avec `ImportError: cannot import name '_convert_flat_source'`

- [ ] **Step 3: Implémenter `_convert_flat_source`**

Ajouter à `src/transformations/raw_to_bronze.py`, après les imports (ajouter `from pathlib import Path` en tête, et `import polars as pl`, et `from ingestion.storage import open_stream`) :

```python
from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from ingestion.storage import open_stream


def _normalize_column_name(name: str) -> str:
    ...  # inchangé, déjà en place depuis Task 1


def _download_to_local(raw_partition: str, object_name: str, work_dir: Path) -> Path:
    """Copie un objet raw vers un fichier local, en flux, sans le charger en mémoire.

    Le nom de fichier local reprend `object_name` (donc son extension `.gz` le cas
    échéant) : Polars détecte la compression gzip d'un CSV local sur l'extension,
    déjà le comportement dont dépend `ingestion.clinvar.filter_clinvar`.
    """
    local_path = work_dir / object_name
    with open_stream(f"{raw_partition}/{object_name}") as src, open(local_path, "wb") as dst:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
    return local_path


def _convert_flat_source(
    raw_partition: str,
    object_name: str,
    technical_columns: dict[str, str],
    work_dir: Path,
) -> Path:
    """Convertit une source flat (TSV) en Parquet, en lazy, sans jamais tout charger.

    Colonnes renommées (mécaniquement), lignes entièrement vides retirées, colonnes
    techniques ajoutées après ce filtre (elles ne sont jamais vides, ce qui
    fausserait la détection d'une ligne vide si elles étaient ajoutées avant).
    """
    local_input = _download_to_local(raw_partition, object_name, work_dir)
    lf = pl.scan_csv(local_input, separator="\t", infer_schema_length=0)
    original_names = lf.collect_schema().names()
    lf = lf.rename({name: _normalize_column_name(name) for name in original_names})
    lf = lf.filter(~pl.all_horizontal(pl.all().is_null()))
    lf = lf.with_columns(
        [pl.lit(value).alias(key) for key, value in technical_columns.items()]
    )
    output_path = work_dir / "output.parquet"
    lf.sink_parquet(output_path)
    return output_path
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/raw_to_bronze.py tests/transformations/test_raw_to_bronze.py
git commit -m "feat: convert flat (TSV) raw sources to bronze Parquet"
```

---

### Task 3: `_convert_jsonl_source` (ncbi_gene, refseq, medgen, hpo_terms)

**Files:**
- Modify: `src/transformations/raw_to_bronze.py`
- Test: `tests/transformations/test_raw_to_bronze.py`

**Interfaces:**
- Consumes: `ingestion.storage.get_bytes`.
- Produces: `transformations.raw_to_bronze._convert_jsonl_source(raw_partition: str, object_name: str, scalar_fields: tuple[str, ...], nested_fields: tuple[str, ...], technical_columns: dict[str, str], work_dir: Path) -> Path`.

**Vérifié à la main avant d'écrire ce plan** : `pl.DataFrame(rows)` sur une liste de dicts de forme uniforme (un champ scalaire + un champ `_json`) construit un DataFrame sans perte de colonne, y compris quand la valeur imbriquée d'origine était `{}` (sérialisée en la chaîne `"{}"`, pas supprimée).

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_raw_to_bronze.py` :

```python
import gzip
import json

from transformations.raw_to_bronze import _convert_jsonl_source

JSONL_OBJECT = "gene_summaries.jsonl.gz"


def _seed_jsonl_object(tmp_path, records):
    partition = f"file://{tmp_path}/lake/raw/ncbi_gene/dt=2026-09-01/panel=brca"
    body = "".join(json.dumps(r) + "\n" for r in records)
    put_bytes(f"{partition}/{JSONL_OBJECT}", gzip.compress(body.encode()))
    return partition


def test_convert_jsonl_source_extracts_scalar_fields_as_columns(tmp_path):
    partition = _seed_jsonl_object(tmp_path, [
        {"gene_symbol": "BRCA1", "esummary": {"uid": "672", "name": "BRCA1"}},
        {"gene_symbol": "HBS1L", "esummary": {}},
    ])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df["gene_symbol"].to_list() == ["BRCA1", "HBS1L"]
    assert df.columns == ["gene_symbol", "esummary_json", "_source_version", "_logical_date", "_ingested_at"]


def test_convert_jsonl_source_serializes_the_nested_field_as_reparsable_json(tmp_path):
    partition = _seed_jsonl_object(tmp_path, [
        {"gene_symbol": "BRCA1", "esummary": {"uid": "672", "name": "BRCA1"}},
    ])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    parsed = json.loads(df["esummary_json"][0])
    assert parsed == {"uid": "672", "name": "BRCA1"}


def test_convert_jsonl_source_keeps_a_row_with_an_empty_nested_payload(tmp_path):
    """Un gène non résolu par NCBI Gene garde sa ligne, esummary vide — pas de ligne
    supprimée (cohérent avec un CUI MedGen non résolu, déjà légitime en raw)."""
    partition = _seed_jsonl_object(tmp_path, [
        {"gene_symbol": "HBS1L", "esummary": {}},
    ])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df["gene_symbol"].to_list() == ["HBS1L"]
    assert json.loads(df["esummary_json"][0]) == {}


def test_convert_jsonl_source_handles_multiple_scalar_and_nested_fields(tmp_path):
    """hpo_terms : trois champs scalaires, un champ imbriqué."""
    partition = f"file://{tmp_path}/lake/raw/hpo_terms/dt=2026-09-01/panel=sickle"
    records = [
        {"gene_symbol": "HBB", "hpo_id": "HP:0001903", "hpo_name": "Anemia",
         "details": {"definition": "A reduction in erythrocytes."}},
    ]
    body = "".join(json.dumps(r) + "\n" for r in records)
    put_bytes(f"{partition}/hpo_terms.jsonl.gz", gzip.compress(body.encode()))
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, "hpo_terms.jsonl.gz",
        ("gene_symbol", "hpo_id", "hpo_name"), ("details",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df.columns == [
        "gene_symbol", "hpo_id", "hpo_name", "details_json",
        "_source_version", "_logical_date", "_ingested_at",
    ]
    assert json.loads(df["details_json"][0])["definition"] == "A reduction in erythrocytes."
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: FAIL avec `ImportError: cannot import name '_convert_jsonl_source'`

- [ ] **Step 3: Implémenter `_convert_jsonl_source`**

Ajouter à `src/transformations/raw_to_bronze.py` (ajouter `import gzip` et `import json` en tête, et `from ingestion.storage import get_bytes, open_stream`) :

```python
import gzip
import json


def _convert_jsonl_source(
    raw_partition: str,
    object_name: str,
    scalar_fields: tuple[str, ...],
    nested_fields: tuple[str, ...],
    technical_columns: dict[str, str],
    work_dir: Path,
) -> Path:
    """Convertit une source JSONL en Parquet : champs scalaires en colonnes, champs
    imbriqués sérialisés en chaîne JSON (`<champ>_json`), jamais aplatis.

    Volume par gène/CUI du panel (quelques dizaines d'enregistrements au plus) :
    traitement en mémoire, pas de mode lazy nécessaire, contrairement aux sources
    flat.
    """
    raw = gzip.decompress(get_bytes(f"{raw_partition}/{object_name}")).decode("utf-8")
    rows: list[dict] = []
    for line in raw.splitlines():
        if not line:
            continue
        record = json.loads(line)
        row = {field: record.get(field) for field in scalar_fields}
        row.update(
            {f"{field}_json": json.dumps(record.get(field)) for field in nested_fields}
        )
        rows.append(row)

    df = pl.DataFrame(rows)
    df = df.with_columns(
        [pl.lit(value).alias(key) for key, value in technical_columns.items()]
    )
    output_path = work_dir / "output.parquet"
    df.write_parquet(output_path)
    return output_path
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/raw_to_bronze.py tests/transformations/test_raw_to_bronze.py
git commit -m "feat: convert JSONL raw sources to bronze Parquet, nested payloads kept as JSON strings"
```

---

### Task 4: Table déclarative et orchestration `raw_to_bronze()`

**Files:**
- Modify: `src/transformations/raw_to_bronze.py`
- Test: `tests/transformations/test_raw_to_bronze.py`

**Interfaces:**
- Consumes: `ingestion.config.{BRONZE, RAW}` ; `ingestion.storage.{begin_partition, build_manifest, finalize_partition, partition_uri, put_file, read_manifest}` ; `_convert_flat_source`/`_convert_jsonl_source` (Tasks 2 et 3).
- Produces: `transformations.raw_to_bronze.raw_to_bronze(logical_date, sources, panel=None, lake_uri=None) -> list[str]` (signature finale, déjà consommée par `dags/dag_acquisition_sources.py` et `dags/dag_genomic_pipeline.py`).

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_raw_to_bronze.py` :

```python
import pytest

from ingestion.config import BRONZE, RAW
from ingestion.storage import (
    begin_partition,
    build_manifest,
    finalize_partition,
    get_bytes,
    partition_is_complete,
    partition_uri,
    put_bytes,
    read_manifest,
)
from transformations.raw_to_bronze import raw_to_bronze


def _seed_raw_flat(lake, source, logical_date, object_name, content: bytes, source_version, panel=None):
    partition = partition_uri(RAW, source, logical_date, panel=panel, lake_uri=lake)
    begin_partition(partition)
    put_bytes(f"{partition}/{object_name}", content)
    finalize_partition(partition, build_manifest(
        source=source, logical_date=logical_date, source_url="https://example.org/src",
        source_version=source_version, files={object_name: len(content)}, record_count=2,
        panel=panel,
    ))
    return partition


def _seed_raw_jsonl(lake, source, logical_date, object_name, records, source_version, panel=None):
    body = gzip.compress("".join(json.dumps(r) + "\n" for r in records).encode())
    return _seed_raw_flat(lake, source, logical_date, object_name, body, source_version, panel=panel)


def _read_bronze_parquet(partition: str) -> pl.DataFrame:
    """Relit le Parquet écrit par raw_to_bronze via l'abstraction de stockage
    (get_bytes), comme le reste des tests du projet — jamais un chemin filesystem
    en dur, pour que ces tests restent valables si le lac passe un jour sur MinIO."""
    return pl.read_parquet(io.BytesIO(get_bytes(f"{partition}/data.parquet")))


def test_raw_to_bronze_converts_a_flat_shared_source(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_flat(
        lake, "hpo", "2026-09-01", "genes_to_phenotype.txt",
        b"ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n3043\tHBB\tHP:0001903\tAnemia\n",
        source_version="v2026.08.01",
    )

    partitions = raw_to_bronze("2026-09-01", ["hpo"], lake_uri=lake)

    assert partitions == [f"{lake}/bronze/hpo/dt=2026-09-01"]
    assert partition_is_complete(partitions[0])
    df = _read_bronze_parquet(partitions[0])
    assert df["gene_symbol"].to_list() == ["HBB"]


def test_raw_to_bronze_converts_a_jsonl_panel_source(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_jsonl(
        lake, "ncbi_gene", "2026-09-01", "gene_summaries.jsonl.gz",
        [{"gene_symbol": "BRCA1", "esummary": {"uid": "672"}}],
        source_version="2026-09-01", panel="brca",
    )

    partitions = raw_to_bronze("2026-09-01", ["ncbi_gene"], panel="brca", lake_uri=lake)

    assert partitions == [f"{lake}/bronze/ncbi_gene/dt=2026-09-01/panel=brca"]
    assert partition_is_complete(partitions[0])


def test_raw_to_bronze_manifest_traces_back_to_the_raw_partition(tmp_path):
    lake = f"file://{tmp_path}/lake"
    raw_partition = _seed_raw_jsonl(
        lake, "medgen", "2026-09-01", "concepts.jsonl.gz",
        [{"cui": "C0002895", "esummary": {"conceptmeta": "<OMIM/>"}}],
        source_version="2026-09-01", panel="sickle",
    )

    [bronze_partition] = raw_to_bronze("2026-09-01", ["medgen"], panel="sickle", lake_uri=lake)

    manifest = read_manifest(bronze_partition)
    assert manifest["source_url"] == raw_partition
    assert manifest["source_version"] == "2026-09-01"
    assert manifest["record_count"] == 1
    assert manifest["panel"] == "sickle"


def test_raw_to_bronze_propagates_technical_columns_from_the_raw_manifest(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_jsonl(
        lake, "refseq", "2026-09-01", "transcripts.jsonl.gz",
        [{"gene_symbol": "BRCA1", "transcripts": [{"accession": "NM_007294"}]}],
        source_version="2026-09-01", panel="brca",
    )

    [bronze_partition] = raw_to_bronze("2026-09-01", ["refseq"], panel="brca", lake_uri=lake)
    raw_manifest = read_manifest(partition_uri(RAW, "refseq", "2026-09-01", panel="brca", lake_uri=lake))

    df = _read_bronze_parquet(bronze_partition)
    assert df["_source_version"].to_list() == [raw_manifest["source_version"]]
    assert df["_logical_date"].to_list() == ["2026-09-01"]
    assert df["_ingested_at"].to_list() == [raw_manifest["written_at"]]


def test_raw_to_bronze_rejects_an_unknown_source(tmp_path):
    lake = f"file://{tmp_path}/lake"
    with pytest.raises(ValueError, match="source inconnue"):
        raw_to_bronze("2026-09-01", ["inconnue"], lake_uri=lake)


def test_raw_to_bronze_converts_every_source_it_is_given(tmp_path):
    """Boucle sur plusieurs sources partagées en un seul appel, comme le fait le DAG
    d'acquisition avec SHARED_SOURCES = ["clinvar", "hpo"]."""
    lake = f"file://{tmp_path}/lake"
    _seed_raw_flat(
        lake, "clinvar", "2026-09-01", "variant_summary.txt.gz",
        gzip.compress(b"#AlleleID\tGeneSymbol\n1\tBRCA1\n"), source_version="2026-09",
    )
    _seed_raw_flat(
        lake, "hpo", "2026-09-01", "genes_to_phenotype.txt",
        b"ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n3043\tHBB\tHP:0001903\tAnemia\n",
        source_version="v2026.08.01",
    )

    partitions = raw_to_bronze("2026-09-01", ["clinvar", "hpo"], lake_uri=lake)

    assert partitions == [
        f"{lake}/bronze/clinvar/dt=2026-09-01",
        f"{lake}/bronze/hpo/dt=2026-09-01",
    ]
    assert all(partition_is_complete(p) for p in partitions)
```

Ajouter en tête du fichier de test, avec les autres imports : `import gzip`, `import io`, `import json`, `import polars as pl`.

Ajouter aussi ce test, pour la règle d'échec partiel du §4 de la spec (une source en
échec ne doit pas empêcher la finalisation des sources précédentes du même appel) :

```python
def test_raw_to_bronze_finalizes_earlier_sources_when_a_later_one_fails(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_flat(
        lake, "hpo", "2026-09-01", "genes_to_phenotype.txt",
        b"ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n3043\tHBB\tHP:0001903\tAnemia\n",
        source_version="v2026.08.01",
    )
    # "inconnue" n'a pas de partition raw : sa conversion échoue avec ValueError,
    # après que "hpo" a déjà été converti et finalisé.

    with pytest.raises(ValueError, match="source inconnue"):
        raw_to_bronze("2026-09-01", ["hpo", "inconnue"], lake_uri=lake)

    hpo_bronze = partition_uri(BRONZE, "hpo", "2026-09-01", lake_uri=lake)
    assert partition_is_complete(hpo_bronze)
    inconnue_bronze = partition_uri(BRONZE, "inconnue", "2026-09-01", lake_uri=lake)
    assert not partition_is_complete(inconnue_bronze)
```

(`BRONZE` et `partition_is_complete` sont déjà dans les imports du bloc ci-dessus.)

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: FAIL — `raw_to_bronze` lève encore `NotImplementedError`

- [ ] **Step 3: Implémenter la table déclarative et `raw_to_bronze()`**

Remplacer la fonction `raw_to_bronze` (le stub `NotImplementedError` de Task 1) par l'implémentation finale. Ajouter aussi en tête du fichier `import tempfile`, `from dataclasses import dataclass`, et `from ingestion.config import BRONZE, RAW` et `from ingestion.storage import begin_partition, build_manifest, finalize_partition, get_bytes, partition_uri, put_file, read_manifest` (en complément de `open_stream` déjà importé en Task 2) :

```python
@dataclass(frozen=True)
class _FlatSource:
    object_name: str


@dataclass(frozen=True)
class _JsonlSource:
    object_name: str
    scalar_fields: tuple[str, ...]
    nested_fields: tuple[str, ...]


# Une source flat : uniquement son nom de fichier raw, converti tel quel colonne
# par colonne. Une source JSONL : en plus, quels champs sont scalaires (colonnes
# directes) et lesquels sont imbriqués (sérialisés en `<champ>_json`).
_FLAT_SOURCES: dict[str, _FlatSource] = {
    "clinvar": _FlatSource("variant_summary.txt.gz"),
    "hpo": _FlatSource("genes_to_phenotype.txt"),
}

_JSONL_SOURCES: dict[str, _JsonlSource] = {
    "ncbi_gene": _JsonlSource("gene_summaries.jsonl.gz", ("gene_symbol",), ("esummary",)),
    "refseq": _JsonlSource("transcripts.jsonl.gz", ("gene_symbol",), ("transcripts",)),
    "medgen": _JsonlSource("concepts.jsonl.gz", ("cui",), ("esummary",)),
    "hpo_terms": _JsonlSource(
        "hpo_terms.jsonl.gz",
        ("gene_symbol", "hpo_id", "hpo_name"),
        ("details",),
    ),
}

OUTPUT_OBJECT_NAME = "data.parquet"


def raw_to_bronze(
    logical_date: str,
    sources: list[str],
    panel: str | None = None,
    lake_uri: str | None = None,
) -> list[str]:
    """Convertit les partitions raw des sources données en Parquet dans la couche bronze.

    ... (docstring de Task 1, conservé tel quel) ...
    """
    partitions: list[str] = []
    for source in sources:
        raw_partition = partition_uri(RAW, source, logical_date, panel=panel, lake_uri=lake_uri)
        bronze_partition = partition_uri(BRONZE, source, logical_date, panel=panel, lake_uri=lake_uri)
        raw_manifest = read_manifest(raw_partition)
        technical_columns = {
            "_source_version": raw_manifest["source_version"],
            "_logical_date": logical_date,
            "_ingested_at": raw_manifest["written_at"],
        }

        begin_partition(bronze_partition)
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            if source in _FLAT_SOURCES:
                spec = _FLAT_SOURCES[source]
                output_path = _convert_flat_source(
                    raw_partition, spec.object_name, technical_columns, work_dir
                )
            elif source in _JSONL_SOURCES:
                spec = _JSONL_SOURCES[source]
                output_path = _convert_jsonl_source(
                    raw_partition, spec.object_name, spec.scalar_fields,
                    spec.nested_fields, technical_columns, work_dir,
                )
            else:
                raise ValueError(f"source inconnue de raw_to_bronze : {source!r}")

            record_count = pl.scan_parquet(output_path).select(pl.len()).collect().item()
            file_size = output_path.stat().st_size
            put_file(f"{bronze_partition}/{OUTPUT_OBJECT_NAME}", output_path)

        finalize_partition(
            bronze_partition,
            build_manifest(
                source=source,
                logical_date=logical_date,
                source_url=raw_partition,
                source_version=raw_manifest["source_version"],
                files={OUTPUT_OBJECT_NAME: file_size},
                record_count=record_count,
                panel=panel,
            ),
        )
        partitions.append(bronze_partition)
    return partitions
```

**Point d'attention.** `file_size` et `record_count` sont calculés **avant** la sortie du bloc `with tempfile.TemporaryDirectory()` (qui supprime `work_dir` à sa sortie) — `output_path.stat()` échouerait sur un fichier déjà supprimé si ce calcul était fait après.

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_raw_to_bronze.py -q`
Expected: PASS, 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/raw_to_bronze.py tests/transformations/test_raw_to_bronze.py
git commit -m "feat: implement raw_to_bronze with a per-source declarative dispatch table"
```

---

### Task 5: Vérification finale

**Files:** aucun changement.

- [ ] **Step 1: Passe rapide complète**

Run: `venv/bin/pytest -q`
Expected: PASS, sans régression (aucun test d'un autre module ne doit avoir changé de comportement)

- [ ] **Step 2: Passe Airflow (structure des DAGs inchangée)**

Run: `venv/bin/pytest tests_airflow -q`
Expected: PASS, 20 passed — ce plan ne touche à aucun fichier de `dags/`, cette passe ne fait que confirmer l'absence de régression involontaire

- [ ] **Step 3: Aucun moteur interdit importé**

Run: `grep -rnE "^(import|from) (deltalake|pyspark|pandas)" src/transformations/raw_to_bronze.py || echo "aucun moteur interdit importe"`
Expected: `aucun moteur interdit importe`

- [ ] **Step 4: Vérification live optionnelle (nécessite Docker)**

Si une vérification en conditions réelles est souhaitée : reconstruire la stack (`docker compose -p rag_genomique --env-file .env up -d --build`), déclencher `dag_acquisition_sources`. Attendu, différent du comportement observé lors de la vérification du sous-projet A : `raw_to_bronze_shared` doit maintenant réussir (plus de stub), `check_bronze_shared` doit réussir, l'Asset `SOURCES_READY` doit être publié. C'est la première fois que ce chemin peut aller au-delà de `check_raw_shared`.

- [ ] **Step 5: Mettre à jour CLAUDE.md**

Dans `CLAUDE.md`, section « Orchestration — Airflow 3 », remplacer la ligne :

```markdown
- `src/transformations/` contient les passages entre couches (stubs tant que les
  sous-projets B, C et D ne sont pas livrés).
```

par :

```markdown
- `src/transformations/` contient les passages entre couches : `raw_to_bronze` livré
  (sous-projet B), `bronze_to_silver`/`silver_to_gold_rag`/`silver_to_gold_analytique`
  restent des stubs (sous-projets C et D).
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark raw_to_bronze as delivered in CLAUDE.md"
```
