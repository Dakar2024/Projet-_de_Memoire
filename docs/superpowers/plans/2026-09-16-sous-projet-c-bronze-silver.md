# Sous-projet C — `bronze → silver` en Polars et Delta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter `bronze_to_silver()` (stub) et `quality_check_silver()` (aujourd'hui un `NotImplementedError` inline dans le DAG, sans fonction dans `src/`) : neuf tables Delta typées à partir du Bronze, avec historique SCD2 sur `clinvar_variant`.

**Architecture :** Neuf fonctions bâtisseuses (une par table), chacune lit son/ses bronze source(s) et produit un DataFrame Polars typé ; une fonction d'écriture Delta générique gère l'overwrite scindé par `panel` pour huit tables, et `clinvar_variant` seule passe par un `MERGE` (SCD2). `bronze_to_silver()` orchestre les neuf. `quality_check_silver()` vit dans son propre fichier et devient une vraie fonction câblée dans le DAG.

**Tech Stack :** Python 3.12, Polars 1.44.1, `deltalake` 1.6.3 (nouvelle dépendance), pytest 9.1.1.

**Spec :** `docs/superpowers/specs/2026-09-16-sous-projet-c-bronze-silver-design.md` (précise `docs/superpowers/specs/2026-09-15-architecture-quatre-couches-design.md`, §3.3, §5, §7).

## Global Constraints

- Signatures figées : `bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None` (déjà fixée par le sous-projet A) ; `quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None` (nouvelle, ce plan la crée).
- Neuf tables Delta **uniques et partagées** entre les deux panels — `silver/<entité>/`, une seule URI par entité, partitionnée en interne par la colonne `panel`. Jamais un chemin par panel comme en raw/bronze.
- `deltalake==1.6.3` dans `requirements.txt`. **Jamais `pyarrow`** — vérifié à la main : `pl.DataFrame.write_delta`/`pl.read_delta` fonctionnent sans, y compris pour le `MERGE`.
- Écriture des huit tables sans historique : `df.write_delta(uri, mode="overwrite", delta_write_options={"partition_by": ["panel"], "predicate": f"panel = '{panel}'"})` — jamais un overwrite de la table entière (écraserait l'autre panel).
- `clinvar_variant` seule a un historique SCD2 (`valid_from`, `valid_to`, `is_current`). Champs surveillés pour déclencher une nouvelle version : exactement `clinical_significance`, `review_status`, `last_evaluated`.
- Colonnes techniques bronze (`_source_version`, `_logical_date`, `_ingested_at`) **ne sont pas propagées** dans les tables Silver — Silver a ses propres conventions (`valid_from` pour `clinvar_variant` ; aucune colonne de fraîcheur pour les huit autres, non demandée par la spec).
- Aucun filtre sur la signification clinique. Aucune normalisation de casse sur HGVS, accessions, symboles de gènes. `rs_dbsnp` est un `Int64`, `-1` quand absent (jamais préfixé `rs` en Silver sauf demande explicite — aucune demandée ici).
- Ne jamais importer `pyspark` ni `pandas`.
- Commentaires, docstrings et messages en français. Imports en tête de fichier (E402).
- `venv/bin/pytest -q` doit rester sous ~3 s, sans réseau ni conteneur — à revérifier à la fin de ce plan, l'écriture Delta locale ayant un coût différent de Parquet simple.

---

## Structure des fichiers

**Modifiés :** `requirements.txt`, `src/transformations/bronze_to_silver.py` (remplace le stub), `dags/dag_genomic_pipeline.py`, `tests/transformations/test_stubs.py`.

**Créés :** `src/transformations/quality_check_silver.py`, `tests/transformations/test_bronze_to_silver.py`, `tests/transformations/test_quality_check_silver.py`.

---

### Task 1 (C1) : Dépendance Delta, nettoyage du stub, écriture générique par panel

**Files:**
- Modify: `requirements.txt`
- Modify: `tests/transformations/test_stubs.py`
- Create: `tests/transformations/test_bronze_to_silver.py`
- Modify: `src/transformations/bronze_to_silver.py`

**Interfaces:**
- Consumes : rien de nouveau.
- Produces : `transformations.bronze_to_silver._read_bronze_table(bronze_partition: str) -> pl.DataFrame` ; `transformations.bronze_to_silver._write_silver_snapshot(df: pl.DataFrame, table_uri: str, panel: str) -> None`.

**Pourquoi retirer le test du stub en premier.** `test_bronze_to_silver_names_sub_project_c` attend un `NotImplementedError` : il échouera pour une mauvaise raison dès que la fonction fait un vrai travail.

- [ ] **Step 1: Ajouter la dépendance**

Dans `requirements.txt`, ajouter la ligne `deltalake==1.6.3` (après `polars`).

Run: `venv/bin/pip install -r requirements-dev.txt`
Expected: installation réussie, aucun conflit (vérifié à la main : `deltalake` 1.6.3 fonctionne avec `polars` 1.44.1 sans `pyarrow`).

- [ ] **Step 2: Retirer le test caduc**

Dans `tests/transformations/test_stubs.py`, retirer la fonction `test_bronze_to_silver_names_sub_project_c` et l'import `from transformations.bronze_to_silver import bronze_to_silver` (devenu inutile). Le fichier ne garde que `test_silver_to_gold_rag_names_sub_project_d` et `test_silver_to_gold_analytique_names_sub_project_d`.

- [ ] **Step 3: Vérifier que la suite passe toujours (stub encore en place)**

Run: `venv/bin/pytest tests/transformations -q`
Expected: PASS, 2 passed (les deux tests de stub restants D)

- [ ] **Step 4: Écrire les tests des fonctions techniques (ils doivent échouer)**

Créer `tests/transformations/test_bronze_to_silver.py` :

```python
import gzip
import json

import polars as pl

from ingestion.storage import put_bytes
from transformations.bronze_to_silver import _read_bronze_table, _write_silver_snapshot


def _seed_bronze_parquet(tmp_path, source, panel, df: pl.DataFrame) -> str:
    partition = f"file://{tmp_path}/lake/bronze/{source}/dt=2026-09-01"
    if panel:
        partition += f"/panel={panel}"
    buf = df.write_parquet(file=None) if False else None
    import io
    b = io.BytesIO()
    df.write_parquet(b)
    put_bytes(f"{partition}/data.parquet", b.getvalue())
    return partition


def test_read_bronze_table_reads_back_the_parquet_file(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["BRCA1"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "brca", df)

    result = _read_bronze_table(partition)

    assert result["gene_symbol"].to_list() == ["BRCA1"]


def test_write_silver_snapshot_only_replaces_the_given_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/ncbi_gene"

    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["BRCA1"], "panel": ["brca"]}), uri, "brca"
    )
    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["HBB"], "panel": ["sickle"]}), uri, "sickle"
    )
    # Un second run sur brca ne doit pas toucher les lignes sickle.
    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["BRCA1", "BRCA2"], "panel": ["brca", "brca"]}),
        uri,
        "brca",
    )

    result = pl.read_delta(uri).sort(["panel", "gene_symbol"])
    assert result["gene_symbol"].to_list() == ["BRCA1", "BRCA2", "HBB"]
    assert result["panel"].to_list() == ["brca", "brca", "sickle"]
```

- [ ] **Step 5: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_read_bronze_table'`

- [ ] **Step 6: Implémenter les fonctions techniques**

Remplacer entièrement le contenu de `src/transformations/bronze_to_silver.py` par :

```python
"""Passage bronze -> silver : neuf tables Delta typées, historique SCD2 sur
`clinvar_variant`. Voir docs/superpowers/specs/2026-09-16-sous-projet-c-bronze-silver-design.md.
"""

from __future__ import annotations

import io

import polars as pl

from ingestion.storage import get_bytes


def _read_bronze_table(bronze_partition: str) -> pl.DataFrame:
    """Relit le Parquet d'une partition bronze (fichier unique `data.parquet`)."""
    return pl.read_parquet(io.BytesIO(get_bytes(f"{bronze_partition}/data.parquet")))


def _write_silver_snapshot(df: pl.DataFrame, table_uri: str, panel: str) -> None:
    """Remplace entièrement les lignes du panel dans une table Silver sans historique.

    `predicate` scinde l'overwrite à la seule partition `panel` courante : sans lui,
    chaque run écraserait la table entière et effacerait l'autre panel.
    """
    df.write_delta(
        table_uri,
        mode="overwrite",
        delta_write_options={"partition_by": ["panel"], "predicate": f"panel = '{panel}'"},
    )
```

- [ ] **Step 7: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 2 passed

- [ ] **Step 8: Commit**

```bash
git add requirements.txt tests/transformations/test_stubs.py tests/transformations/test_bronze_to_silver.py src/transformations/bronze_to_silver.py
git commit -m "feat: add deltalake dependency and generic per-panel Silver snapshot writer"
```

---

### Task 2 (C2) : `clinvar_variant_gene`

**Files:**
- Modify: `src/transformations/bronze_to_silver.py`
- Test: `tests/transformations/test_bronze_to_silver.py`

**Interfaces:**
- Consumes : `_read_bronze_table` (Task 1) ; `ingestion.storage.partition_uri` ; `ingestion.config.BRONZE`.
- Produces : `transformations.bronze_to_silver._build_clinvar_variant_gene(bronze_partition: str, genes: list[str]) -> pl.DataFrame` — colonnes `alleleid`, `gene_symbol` ; une ligne par (variant, gène) du panel.

**Pourquoi cette table en premier.** `clinvar_variant_gene` détermine quels `alleleid` appartiennent au panel (éclatement de `genesymbol`, qui peut joindre plusieurs gènes par `;`) — `clinvar_variant` (Task 3) s'appuie dessus pour son propre filtre panel.

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
from transformations.bronze_to_silver import _build_clinvar_variant_gene

CLINVAR_ROWS = pl.DataFrame({
    "alleleid": ["1", "2", "3"],
    "genesymbol": ["BRCA1", "ATM;PTEN", "HBB"],
    "assembly": ["GRCh38", "GRCh38", "GRCh38"],
})


def _seed_clinvar_bronze(tmp_path, df: pl.DataFrame = CLINVAR_ROWS) -> str:
    return _seed_bronze_parquet(tmp_path, "clinvar", None, df)


def test_build_clinvar_variant_gene_explodes_multi_gene_rows(tmp_path):
    partition = _seed_clinvar_bronze(tmp_path)

    result = _build_clinvar_variant_gene(partition, ["BRCA1", "ATM", "PTEN"])

    pairs = sorted(zip(result["alleleid"].to_list(), result["gene_symbol"].to_list()))
    assert pairs == [("1", "BRCA1"), ("2", "ATM"), ("2", "PTEN")]


def test_build_clinvar_variant_gene_excludes_genes_outside_the_panel(tmp_path):
    partition = _seed_clinvar_bronze(tmp_path)

    result = _build_clinvar_variant_gene(partition, ["BRCA1"])

    assert result["gene_symbol"].to_list() == ["BRCA1"]
```

Note : `_seed_bronze_parquet` de Task 1 accepte `panel=None` pour une source partagée
(pas de suffixe `/panel=` dans le chemin), cohérent avec `partition_uri(..., panel=None)`.

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_build_clinvar_variant_gene'`

- [ ] **Step 3: Implémenter**

Ajouter à `src/transformations/bronze_to_silver.py` :

```python
def _build_clinvar_variant_gene(bronze_partition: str, genes: list[str]) -> pl.DataFrame:
    """Éclate `genesymbol` (jointure `;` pour les variants multi-gènes) et filtre au panel.

    C'est cette table, et non `clinvar_variant`, qui décide quels `alleleid`
    appartiennent au panel : `clinvar_variant` la consulte plutôt que de refiltrer
    `genesymbol` elle-même.
    """
    df = _read_bronze_table(bronze_partition)
    exploded = (
        df.select(["alleleid", "genesymbol"])
        .with_columns(pl.col("genesymbol").str.split(";").alias("gene_symbol"))
        .explode("gene_symbol")
        .drop("genesymbol")
    )
    return exploded.filter(pl.col("gene_symbol").is_in(genes))
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/bronze_to_silver.py tests/transformations/test_bronze_to_silver.py
git commit -m "feat: build clinvar_variant_gene, exploding multi-gene ClinVar rows"
```

---

### Task 3 (C3) : `clinvar_variant` — filtre, typage, HGVS, historique SCD2

**Files:**
- Modify: `src/transformations/bronze_to_silver.py`
- Test: `tests/transformations/test_bronze_to_silver.py`

**Interfaces:**
- Consumes : `_read_bronze_table`, `_build_clinvar_variant_gene` (Tasks 1-2).
- Produces : `transformations.bronze_to_silver._build_clinvar_variant_rows(bronze_partition: str, refseq_df: pl.DataFrame, variant_gene: pl.DataFrame) -> pl.DataFrame` (une ligne par variant du panel, sans historique) ; `transformations.bronze_to_silver._write_clinvar_variant(rows: pl.DataFrame, table_uri: str, panel: str, logical_date: str) -> None` (le `MERGE` SCD2).

**Vérifié à la main avant d'écrire ce plan** (Polars 1.44.1, `deltalake` 1.6.3, sans `pyarrow`) : le mécanisme `MERGE` en deux lignes par variant changé (une `close` avec `merge_key = alleleid`, une `insert_new` avec `merge_key = null` pour forcer l'insertion) fonctionne, y compris pour la création initiale de la table et le rejeu idempotent (un rejeu à valeurs identiques ne crée aucune ligne d'historique supplémentaire).

- [ ] **Step 1: Écrire les tests de construction des lignes (sans l'historique) — ils doivent échouer**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
from transformations.bronze_to_silver import _build_clinvar_variant_rows

REFSEQ_ROWS = pl.DataFrame({
    "gene_symbol": ["AP5Z1"],
    "accession": ["NM_014855"],
    "version": [3],
})


def test_build_clinvar_variant_rows_keeps_only_grch38(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1", "1"],
        "genesymbol": ["AP5Z1", "AP5Z1"],
        "assembly": ["GRCh37", "GRCh38"],
        "clinicalsignificance": ["Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["397704705", "397704705"],
        "name": [
            "NM_014855.3(AP5Z1):c.80_83delinsTGCTG",
            "NM_014855.3(AP5Z1):c.80_83delinsTGCTG",
        ],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)

    assert result["alleleid"].to_list() == ["1"]
    assert result["assembly"].to_list() == ["GRCh38"]


def test_build_clinvar_variant_rows_deduplicates_on_alleleid(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1", "1"],
        "genesymbol": ["AP5Z1", "AP5Z1"],
        "assembly": ["GRCh38", "GRCh38"],
        "clinicalsignificance": ["Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["-1", "-1"],
        "name": ["NM_014855.3(AP5Z1):c.1A>G", "NM_014855.3(AP5Z1):c.1A>G"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)

    assert len(result) == 1


def test_build_clinvar_variant_rows_casts_rs_dbsnp_to_integer_with_sentinel(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_014855.3(AP5Z1):c.1A>G"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)

    assert result["rs_dbsnp"].to_list() == [-1]
    assert result.schema["rs_dbsnp"] == pl.Int64


def test_build_clinvar_variant_rows_parses_hgvs_and_validates_against_refseq(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_014855.3(AP5Z1):c.80_83delinsTGCTG"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)
    row = result.row(0, named=True)

    assert row["refseq_accession"] == "NM_014855"
    assert row["refseq_version"] == 3
    assert row["hgvs_c"] == "c.80_83delinsTGCTG"
    assert row["hgvs_p"] is None
    assert row["refseq_accession_known"] is True


def test_build_clinvar_variant_rows_keeps_a_row_with_irregular_hgvs(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["forme HGVS non reconnue"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)
    row = result.row(0, named=True)

    assert row["name"] == "forme HGVS non reconnue"
    assert row["refseq_accession"] is None
    assert row["refseq_accession_known"] is False
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_build_clinvar_variant_rows'`

- [ ] **Step 3: Implémenter `_build_clinvar_variant_rows`**

Ajouter à `src/transformations/bronze_to_silver.py` (ajouter `import re` en tête) :

```python
import re

# `NM_014855.3(AP5Z1):c.80_83delinsTGCTG` -> accession, version, gène, HGVS coding.
# Le HGVS protéique, s'il existe, apparaît entre parenthèses après le HGVS coding
# (ex. "...c.1A>G (p.Met1?)") : capturé séparément, absent la plupart du temps.
_HGVS_PATTERN = re.compile(
    r"^(?P<accession>[A-Z]+_\d+)\.(?P<version>\d+)\([^)]+\):(?P<hgvs_c>[^\s(]+)"
    r"(?:\s*\((?P<hgvs_p>p\.[^)]+)\))?"
)


def _parse_hgvs(name: str) -> dict:
    match = _HGVS_PATTERN.match(name)
    if not match:
        return {"refseq_accession": None, "refseq_version": None, "hgvs_c": None, "hgvs_p": None}
    return {
        "refseq_accession": match.group("accession"),
        "refseq_version": int(match.group("version")),
        "hgvs_c": match.group("hgvs_c"),
        "hgvs_p": match.group("hgvs_p"),
    }


def _build_clinvar_variant_rows(
    bronze_partition: str, refseq_df: pl.DataFrame, variant_gene: pl.DataFrame
) -> pl.DataFrame:
    """Une ligne par variant du panel, sans l'historique SCD2 (ajouté à l'écriture).

    Filtre GRCh38, dédoublonnage sur `alleleid`, `rs_dbsnp` en entier, HGVS parsé et
    validé contre le catalogue RefSeq du panel. Ne filtre jamais sur la signification
    clinique.
    """
    df = _read_bronze_table(bronze_partition)
    panel_ids = variant_gene["alleleid"].unique()

    filtered = (
        df.filter(pl.col("alleleid").is_in(panel_ids))
        .filter(pl.col("assembly") == "GRCh38")
        .unique(subset=["alleleid"], keep="first", maintain_order=True)
        .with_columns(pl.col("rs_dbsnp").cast(pl.Int64))
    )

    parsed = [
        {"alleleid": row["alleleid"], **_parse_hgvs(row["name"])}
        for row in filtered.select(["alleleid", "name"]).to_dicts()
    ]
    hgvs_df = pl.DataFrame(
        parsed,
        schema={
            "alleleid": pl.Utf8, "refseq_accession": pl.Utf8,
            "refseq_version": pl.Int64, "hgvs_c": pl.Utf8, "hgvs_p": pl.Utf8,
        },
    )

    known_accessions = set(refseq_df["accession"].to_list())
    hgvs_df = hgvs_df.with_columns(
        pl.col("refseq_accession").is_in(known_accessions).alias("refseq_accession_known")
    )

    return filtered.join(hgvs_df, on="alleleid")
```

- [ ] **Step 4: Vérifier que les tests de construction passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Écrire les tests de l'historique SCD2 (ils doivent échouer)**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
from transformations.bronze_to_silver import _write_clinvar_variant

SCD2_COLS = [
    "alleleid", "panel", "clinicalsignificance", "reviewstatus", "lastevaluated",
]


def _rows(alleleid, panel, significance, review="criteria provided", evaluated="2026-08-01"):
    return pl.DataFrame({
        "alleleid": [alleleid], "panel": [panel],
        "clinicalsignificance": [significance], "reviewstatus": [review],
        "lastevaluated": [evaluated],
    })


def test_write_clinvar_variant_creates_the_table_on_first_run(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"

    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")

    result = pl.read_delta(uri)
    assert result["is_current"].to_list() == [True]
    assert result["valid_from"].to_list() == ["2026-08-01"]
    assert result["valid_to"].to_list() == [None]


def test_write_clinvar_variant_closes_and_reopens_on_a_real_change(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-08-01")

    _write_clinvar_variant(
        _rows("1", "brca", "Pathogenic/Likely pathogenic"), uri, "brca", "2026-09-01"
    )

    result = pl.read_delta(uri).sort("valid_from")
    assert result["is_current"].to_list() == [False, True]
    assert result["valid_to"].to_list() == ["2026-09-01", None]
    assert result["clinicalsignificance"].to_list() == [
        "Pathogenic", "Pathogenic/Likely pathogenic",
    ]


def test_write_clinvar_variant_replay_is_idempotent(tmp_path):
    """Rejouer le même mois avec les mêmes valeurs ne doit créer aucune ligne."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    assert len(pl.read_delta(uri)) == 2


def test_write_clinvar_variant_ignores_unwatched_field_changes(tmp_path):
    """Un champ hors liste surveillée (ex. `name`) ne doit pas déclencher de nouvelle
    version — seuls clinical_significance/review_status/last_evaluated comptent."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    first = _rows("1", "brca", "Benign").with_columns(pl.lit("Name v1").alias("name"))
    _write_clinvar_variant(first, uri, "brca", "2026-08-01")

    second = _rows("1", "brca", "Benign").with_columns(pl.lit("Name v2").alias("name"))
    _write_clinvar_variant(second, uri, "brca", "2026-09-01")

    assert len(pl.read_delta(uri)) == 1


def test_write_clinvar_variant_does_not_touch_the_other_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "sickle", "Benign"), uri, "sickle", "2026-08-01")

    _write_clinvar_variant(_rows("2", "brca", "Pathogenic"), uri, "brca", "2026-08-01")

    result = pl.read_delta(uri).sort("panel")
    assert result["panel"].to_list() == ["brca", "sickle"]
    assert result.filter(pl.col("panel") == "sickle")["clinicalsignificance"].to_list() == ["Benign"]
```

- [ ] **Step 6: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_write_clinvar_variant'`

- [ ] **Step 7: Implémenter `_write_clinvar_variant`**

Ajouter à `src/transformations/bronze_to_silver.py` (ajouter `from deltalake import DeltaTable` en tête) :

```python
from deltalake import DeltaTable

# Seuls ces champs, mesurés comme ayant varié d'un mois à l'autre (spec du 15/09,
# §2.2), déclenchent une nouvelle version SCD2. Un autre champ qui change (ex. `name`
# retraité par NCBI) n'est pas une reclassification et ne doit pas en créer une.
_CLINVAR_WATCHED_FIELDS = ["clinicalsignificance", "reviewstatus", "lastevaluated"]


def _write_clinvar_variant(
    rows: pl.DataFrame, table_uri: str, panel: str, logical_date: str
) -> None:
    """Écrit `clinvar_variant` avec historique SCD2 : MERGE si la table existe déjà
    (pour n'importe quel panel), création directe sinon.

    `rows` doit déjà porter une colonne `panel` — comme pour `_write_silver_snapshot`,
    c'est à l'appelant de l'ajouter (cohérent avec l'orchestration de `bronze_to_silver`,
    qui l'ajoute de la même façon aux huit autres tables avant d'écrire).

    Le rejeu du même mois est idempotent : un variant dont les champs surveillés
    n'ont pas changé ne génère aucune ligne — voir `_CLINVAR_WATCHED_FIELDS`.
    """
    if not DeltaTable.is_deltatable(table_uri):
        initial = rows.with_columns([
            pl.lit(logical_date).alias("valid_from"),
            pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
            pl.lit(True).alias("is_current"),
        ])
        # Toutes les colonnes ClinVar d'origine sont conservées (Silver type, il ne
        # retire jamais une colonne) — seules les trois colonnes SCD2 sont ajoutées.
        initial.write_delta(
            table_uri, mode="overwrite", delta_write_options={"partition_by": ["panel"]}
        )
        return

    current = pl.read_delta(table_uri).filter(pl.col("is_current") & (pl.col("panel") == panel))
    current_ids = current["alleleid"].to_list()

    joined = rows.join(
        current.select(["alleleid"] + _CLINVAR_WATCHED_FIELDS).rename(
            {f: f"cur_{f}" for f in _CLINVAR_WATCHED_FIELDS}
        ),
        on="alleleid",
        how="left",
    )
    changed = pl.any_horizontal(
        [pl.col(f) != pl.col(f"cur_{f}") for f in _CLINVAR_WATCHED_FIELDS]
    ) | pl.col(f"cur_{_CLINVAR_WATCHED_FIELDS[0]}").is_null()
    to_process = joined.filter(changed).drop([f"cur_{f}" for f in _CLINVAR_WATCHED_FIELDS])

    if len(to_process) == 0:
        return

    close_rows = to_process.filter(pl.col("alleleid").is_in(current_ids)).with_columns([
        pl.col("alleleid").alias("merge_key"),
        pl.lit("close").alias("action"),
        pl.lit(None, dtype=pl.Utf8).alias("valid_from"),
        pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
        pl.lit(False).alias("is_current"),
    ])
    insert_rows = to_process.with_columns([
        pl.lit(None, dtype=pl.Utf8).alias("merge_key"),
        pl.lit("insert_new").alias("action"),
        pl.lit(logical_date).alias("valid_from"),
        pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
        pl.lit(True).alias("is_current"),
    ])
    staged = pl.concat([close_rows, insert_rows], how="vertical")

    merger = staged.write_delta(
        table_uri,
        mode="merge",
        delta_merge_options={
            "predicate": (
                "target.alleleid = source.merge_key AND target.panel = source.panel "
                "AND target.is_current = true"
            ),
            "source_alias": "source",
            "target_alias": "target",
        },
    )
    # Toutes les colonnes réelles, hors les deux colonnes techniques du merge lui-même
    # (`merge_key`, `action`) qui n'ont pas leur place dans la table finale.
    write_cols = [c for c in staged.columns if c not in ("merge_key", "action")]
    (
        merger.when_matched_update(
            updates={"is_current": "false", "valid_to": f"'{logical_date}'"},
            predicate="source.action = 'close'",
        )
        .when_not_matched_insert(
            updates={c: f"source.{c}" for c in write_cols},
            predicate="source.action = 'insert_new'",
        )
        .execute()
    )
```

**Point d'attention.** Le prédicat du `MERGE` inclut `target.panel = source.panel` : un
`MERGE` sans ce filtre pourrait, en théorie, faire correspondre un `alleleid` d'un autre
panel si jamais les mêmes ID se recoupaient entre panels (pas le cas ici, les deux panels
portent des gènes disjoints, mais le filtre coûte rien et documente l'intention).

- [ ] **Step 8: Vérifier que les tests SCD2 passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 14 passed

- [ ] **Step 9: Commit**

```bash
git add src/transformations/bronze_to_silver.py tests/transformations/test_bronze_to_silver.py
git commit -m "feat: build clinvar_variant with HGVS parsing and SCD2 reclassification history"
```

---

### Task 4 (C4) : `ncbi_gene` et `refseq_transcript`

**Files:**
- Modify: `src/transformations/bronze_to_silver.py`
- Test: `tests/transformations/test_bronze_to_silver.py`

**Interfaces:**
- Consumes : `_read_bronze_table` (Task 1).
- Produces : `transformations.bronze_to_silver._build_ncbi_gene(bronze_partition: str) -> pl.DataFrame` ; `transformations.bronze_to_silver._build_refseq_transcript(bronze_partition: str) -> pl.DataFrame`.

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
import json as _json

from transformations.bronze_to_silver import _build_ncbi_gene, _build_refseq_transcript


def test_build_ncbi_gene_extracts_known_esummary_fields(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["HBB"],
        "esummary_json": [_json.dumps({
            "name": "HBB", "description": "hemoglobin subunit beta",
            "maplocation": "11p15.4", "summary": "This gene encodes beta-globin.",
        })],
    })
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "sickle", df)

    result = _build_ncbi_gene(partition)
    row = result.row(0, named=True)

    assert row["gene_symbol"] == "HBB"
    assert row["name"] == "HBB"
    assert row["description"] == "hemoglobin subunit beta"
    assert row["maplocation"] == "11p15.4"


def test_build_ncbi_gene_keeps_a_row_for_an_unresolved_gene(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["HBS1L"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "sickle", df)

    result = _build_ncbi_gene(partition)

    assert result["gene_symbol"].to_list() == ["HBS1L"]
    assert result["name"].to_list() == [None]


def test_build_refseq_transcript_explodes_one_row_per_transcript(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["BRCA2"],
        "transcripts_json": [_json.dumps([
            {"accessionversion": "NM_001432077.1", "slen": 11863},
            {"accessionversion": "NM_000059.4", "slen": 11986},
        ])],
    })
    partition = _seed_bronze_parquet(tmp_path, "refseq", "brca", df)

    result = _build_refseq_transcript(partition).sort("accession")

    assert result["accession"].to_list() == ["NM_000059", "NM_001432077"]
    assert result["version"].to_list() == [4, 1]
    assert result["gene_symbol"].to_list() == ["BRCA2", "BRCA2"]


def test_build_refseq_transcript_keeps_a_gene_with_no_transcript(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["HBS1L"], "transcripts_json": ["[]"]})
    partition = _seed_bronze_parquet(tmp_path, "refseq", "sickle", df)

    result = _build_refseq_transcript(partition)

    assert len(result) == 0
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_build_ncbi_gene'`

- [ ] **Step 3: Implémenter**

Ajouter à `src/transformations/bronze_to_silver.py` (ajouter `import json` en tête) :

```python
import json


def _build_ncbi_gene(bronze_partition: str) -> pl.DataFrame:
    """Extrait les champs connus d'`esummary_json`. Un gène non résolu (esummary
    vide) garde sa ligne, champs nuls — le verdict qualité appartient à
    `quality_check_silver`, pas à cette étape."""
    df = _read_bronze_table(bronze_partition)
    rows = [
        {
            "gene_symbol": row["gene_symbol"],
            **{
                field: json.loads(row["esummary_json"]).get(field)
                for field in ("name", "description", "maplocation", "summary")
            },
        }
        for row in df.to_dicts()
    ]
    return pl.DataFrame(rows)


def _build_refseq_transcript(bronze_partition: str) -> pl.DataFrame:
    """Éclate `transcripts_json` (une ligne par transcrit), sépare `accessionversion`
    (`"NM_007294.4"`) en `accession` + `version`. Un gène sans transcrit ne produit
    aucune ligne (liste vide), sans que ce soit une erreur."""
    df = _read_bronze_table(bronze_partition)
    rows = []
    for row in df.to_dicts():
        for transcript in json.loads(row["transcripts_json"]):
            accession, _, version = transcript["accessionversion"].partition(".")
            rows.append({
                "gene_symbol": row["gene_symbol"],
                "accession": accession,
                "version": int(version) if version else None,
            })
    return pl.DataFrame(rows, schema={"gene_symbol": pl.Utf8, "accession": pl.Utf8, "version": pl.Int64})
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/bronze_to_silver.py tests/transformations/test_bronze_to_silver.py
git commit -m "feat: build ncbi_gene and refseq_transcript Silver tables"
```

---

### Task 5 (C5) : `medgen_concept`, `medgen_mim`, `medgen_inheritance`

**Files:**
- Modify: `src/transformations/bronze_to_silver.py`
- Test: `tests/transformations/test_bronze_to_silver.py`

**Interfaces:**
- Consumes : `_read_bronze_table` (Task 1) ; `ingestion.medgen.parse_medgen_conceptmeta` (déjà livrée, sous-projet A).
- Produces : `transformations.bronze_to_silver._build_medgen_tables(bronze_partition: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]` — `(medgen_concept, medgen_mim, medgen_inheritance)`, dans cet ordre.

**Pourquoi une seule fonction pour les trois tables.** Les trois viennent du même parsing
XML par CUI (`parse_medgen_conceptmeta`, un appel coûteux à ne pas dupliquer trois fois) ;
séparer les construire romprait ce partage sans bénéfice, puisque les trois tables ne sont
jamais consommées indépendamment de ce parsing.

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
from transformations.bronze_to_silver import _build_medgen_tables

CONCEPTMETA_TWO_MIM = (
    "<OMIM><MIM>603903</MIM></OMIM><OMIM><MIM>141900</MIM></OMIM>"
    "<ModeOfInheritance><Name>Autosomal recessive inheritance</Name></ModeOfInheritance>"
)


def test_build_medgen_tables_reuses_parse_medgen_conceptmeta(tmp_path):
    df = pl.DataFrame({
        "cui": ["C0002895"],
        "esummary_json": [_json.dumps({"conceptid": "C0002895", "conceptmeta": CONCEPTMETA_TWO_MIM})],
    })
    partition = _seed_bronze_parquet(tmp_path, "medgen", "sickle", df)

    concept, mim, inheritance = _build_medgen_tables(partition)

    assert concept["cui"].to_list() == ["C0002895"]
    assert concept["conceptmeta_xml"].to_list() == [CONCEPTMETA_TWO_MIM]
    assert sorted(mim["mim_number"].to_list()) == ["141900", "603903"]
    assert inheritance["mode_inheritance"].to_list() == ["Autosomal recessive inheritance"]


def test_build_medgen_tables_keeps_an_unresolved_cui_without_exploding_rows(tmp_path):
    df = pl.DataFrame({"cui": ["C9999999"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "medgen", "sickle", df)

    concept, mim, inheritance = _build_medgen_tables(partition)

    assert concept["cui"].to_list() == ["C9999999"]
    assert concept["conceptmeta_xml"].to_list() == [None]
    assert len(mim) == 0
    assert len(inheritance) == 0
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_build_medgen_tables'`

- [ ] **Step 3: Implémenter**

Ajouter à `src/transformations/bronze_to_silver.py` :

```python
from ingestion.medgen import parse_medgen_conceptmeta


def _build_medgen_tables(bronze_partition: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Parse `esummary_json.conceptmeta` (réutilise `parse_medgen_conceptmeta`, déjà
    testée) pour produire `medgen_concept`, `medgen_mim` et `medgen_inheritance`.

    Un CUI non résolu (`esummary_json` vide) garde sa ligne dans `medgen_concept`,
    XML nul, et n'explose aucune ligne dans les deux autres tables."""
    df = _read_bronze_table(bronze_partition)

    concept_rows, mim_rows, inheritance_rows = [], [], []
    for row in df.to_dicts():
        esummary = json.loads(row["esummary_json"])
        conceptmeta = esummary.get("conceptmeta")
        parsed = parse_medgen_conceptmeta(conceptmeta) if conceptmeta else {
            "mim_number": None, "mim_numbers": [], "mode_inheritance": None,
            "modes_inheritance": [], "clinical_summary": None, "definitions": [],
        }
        concept_rows.append({
            "cui": row["cui"],
            "conceptmeta_xml": conceptmeta,
            "mim_number": parsed["mim_number"] or None,
            "mode_inheritance": parsed["mode_inheritance"] or None,
            "clinical_summary": parsed["clinical_summary"] or None,
        })
        mim_rows.extend({"cui": row["cui"], "mim_number": mim} for mim in parsed["mim_numbers"])
        inheritance_rows.extend(
            {"cui": row["cui"], "mode_inheritance": mode} for mode in parsed["modes_inheritance"]
        )

    return (
        pl.DataFrame(concept_rows),
        pl.DataFrame(mim_rows, schema={"cui": pl.Utf8, "mim_number": pl.Utf8}),
        pl.DataFrame(inheritance_rows, schema={"cui": pl.Utf8, "mode_inheritance": pl.Utf8}),
    )
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 20 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/bronze_to_silver.py tests/transformations/test_bronze_to_silver.py
git commit -m "feat: build medgen_concept, medgen_mim and medgen_inheritance, reusing parse_medgen_conceptmeta"
```

---

### Task 6 (C6) : `hpo_gene_phenotype` et `hpo_term`

**Files:**
- Modify: `src/transformations/bronze_to_silver.py`
- Test: `tests/transformations/test_bronze_to_silver.py`

**Interfaces:**
- Consumes : `_read_bronze_table` (Task 1).
- Produces : `transformations.bronze_to_silver._build_hpo_gene_phenotype(bronze_partition: str, genes: list[str]) -> pl.DataFrame` ; `transformations.bronze_to_silver._build_hpo_term(bronze_partition: str) -> pl.DataFrame`.

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
from transformations.bronze_to_silver import _build_hpo_gene_phenotype, _build_hpo_term


def test_build_hpo_gene_phenotype_filters_to_the_panel(tmp_path):
    df = pl.DataFrame({
        "ncbi_gene_id": ["3043", "9999"],
        "gene_symbol": ["HBB", "AUTRE"],
        "hpo_id": ["HP:0001903", "HP:0000118"],
        "hpo_name": ["Anemia", "Phenotypic abnormality"],
    })
    partition = _seed_bronze_parquet(tmp_path, "hpo", None, df)

    result = _build_hpo_gene_phenotype(partition, ["HBB"])

    assert result["gene_symbol"].to_list() == ["HBB"]
    assert result["hpo_id"].to_list() == ["HP:0001903"]


def test_build_hpo_term_extracts_details(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["HBB"], "hpo_id": ["HP:0001903"], "hpo_name": ["Anemia"],
        "details_json": [_json.dumps({
            "definition": "A reduction in erythrocytes.",
            "synonyms": ["Low blood count"], "xrefs": ["UMLS:C0002871"],
        })],
    })
    partition = _seed_bronze_parquet(tmp_path, "hpo_terms", "sickle", df)

    result = _build_hpo_term(partition)
    row = result.row(0, named=True)

    assert row["hpo_id"] == "HP:0001903"
    assert row["definition"] == "A reduction in erythrocytes."
    assert row["synonyms"] == ["Low blood count"]


def test_build_hpo_term_keeps_a_row_with_empty_details(tmp_path):
    df = pl.DataFrame({
        "gene_symbol": ["HBB"], "hpo_id": ["HP:0009999"], "hpo_name": ["Terme retire"],
        "details_json": ["{}"],
    })
    partition = _seed_bronze_parquet(tmp_path, "hpo_terms", "sickle", df)

    result = _build_hpo_term(partition)

    assert result["hpo_id"].to_list() == ["HP:0009999"]
    assert result["definition"].to_list() == [None]
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL avec `ImportError: cannot import name '_build_hpo_gene_phenotype'`

- [ ] **Step 3: Implémenter**

Ajouter à `src/transformations/bronze_to_silver.py` :

```python
def _build_hpo_gene_phenotype(bronze_partition: str, genes: list[str]) -> pl.DataFrame:
    """Filtre le fichier plat HPO partagé aux gènes du panel. Un panel sans aucune
    ligne (HBS1L, MYB) produit une table vide, légitime — voir `quality_check_silver`."""
    df = _read_bronze_table(bronze_partition)
    return df.filter(pl.col("gene_symbol").is_in(genes))


def _build_hpo_term(bronze_partition: str) -> pl.DataFrame:
    """Extrait `definition`/`synonyms`/`xrefs` de `details_json`. Un terme retiré de
    HPO (details vide) garde sa ligne, champs nuls."""
    df = _read_bronze_table(bronze_partition)
    rows = []
    for row in df.to_dicts():
        details = json.loads(row["details_json"])
        rows.append({
            "gene_symbol": row["gene_symbol"],
            "hpo_id": row["hpo_id"],
            "hpo_name": row["hpo_name"],
            "definition": details.get("definition") or None,
            "synonyms": details.get("synonyms") or [],
            "xrefs": details.get("xrefs") or [],
        })
    return pl.DataFrame(rows)
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 23 passed

- [ ] **Step 5: Commit**

```bash
git add src/transformations/bronze_to_silver.py tests/transformations/test_bronze_to_silver.py
git commit -m "feat: build hpo_gene_phenotype and hpo_term Silver tables"
```

---

### Task 7 (C7) : Orchestration `bronze_to_silver()`

**Files:**
- Modify: `src/transformations/bronze_to_silver.py`
- Test: `tests/transformations/test_bronze_to_silver.py`

**Interfaces:**
- Consumes : les neuf bâtisseurs (Tasks 2-6), `_write_silver_snapshot`/`_write_clinvar_variant` (Tasks 1, 3) ; `ingestion.config.{BRONZE, RAW}` (RAW inutile ici, seul BRONZE compte) ; `ingestion.storage.partition_uri`.
- Produces : `transformations.bronze_to_silver.bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None` (signature finale, déjà consommée par `dags/dag_genomic_pipeline.py`).

- [ ] **Step 1: Écrire le test d'intégration (il doit échouer)**

Ajouter à `tests/transformations/test_bronze_to_silver.py` :

```python
from transformations.bronze_to_silver import bronze_to_silver


def _seed_all_bronze(tmp_path, lake, panel):
    _seed_bronze_parquet(tmp_path, "clinvar", None, pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["HBB"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_000518.5(HBB):c.1A>G"],
    }))
    _seed_bronze_parquet(tmp_path, "hpo", None, pl.DataFrame({
        "ncbi_gene_id": ["3043"], "gene_symbol": ["HBB"],
        "hpo_id": ["HP:0001903"], "hpo_name": ["Anemia"],
    }))
    _seed_bronze_parquet(tmp_path, "ncbi_gene", panel, pl.DataFrame({
        "gene_symbol": ["HBB"], "esummary_json": [_json.dumps({"name": "HBB"})],
    }))
    _seed_bronze_parquet(tmp_path, "refseq", panel, pl.DataFrame({
        "gene_symbol": ["HBB"],
        "transcripts_json": [_json.dumps([{"accessionversion": "NM_000518.5", "slen": 1000}])],
    }))
    _seed_bronze_parquet(tmp_path, "medgen", panel, pl.DataFrame({
        "cui": ["C0002895"], "esummary_json": [_json.dumps({"conceptid": "C0002895"})],
    }))
    _seed_bronze_parquet(tmp_path, "hpo_terms", panel, pl.DataFrame({
        "gene_symbol": ["HBB"], "hpo_id": ["HP:0001903"], "hpo_name": ["Anemia"],
        "details_json": [_json.dumps({"definition": "A reduction in erythrocytes."})],
    }))


SILVER_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "ncbi_gene", "refseq_transcript",
    "medgen_concept", "medgen_mim", "medgen_inheritance", "hpo_gene_phenotype", "hpo_term",
]


def test_bronze_to_silver_writes_all_nine_tables(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle")

    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    for table in SILVER_TABLES:
        result = pl.read_delta(f"{lake}/silver/{table}")
        assert "panel" in result.columns
        assert set(result["panel"].to_list()) <= {"sickle"}


def test_bronze_to_silver_does_not_disturb_the_other_panel(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_all_bronze(tmp_path, lake, "sickle")
    bronze_to_silver("2026-09-01", "sickle", lake_uri=lake)

    _seed_all_bronze(tmp_path, lake, "brca")
    bronze_to_silver("2026-09-01", "brca", lake_uri=lake)

    result = pl.read_delta(f"{lake}/silver/ncbi_gene")
    assert set(result["panel"].to_list()) == {"brca", "sickle"}
```

`PANELS` (gènes par panel) est nécessaire pour filtrer `clinvar_variant_gene` et
`hpo_gene_phenotype` — importé depuis `dags.common.panels`. **Attention** : `src/`
n'importe normalement jamais depuis `dags/` (sens de dépendance inverse à la règle du
projet). Éviter ce sens en import ant les deux listes de gènes directement depuis
`ingestion.config` (`BREAST_CANCER_GENES`, `SICKLE_CELL_GENES`), qui est déjà la source
de vérité que `dags/common/panels.py` lui-même réexporte — pas de nouvelle dépendance
circulaire.

- [ ] **Step 2: Vérifier qu'il échoue**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: FAIL — `bronze_to_silver` lève encore `NotImplementedError`

- [ ] **Step 3: Implémenter `bronze_to_silver`**

Remplacer la fonction `bronze_to_silver` (le stub) par, et ajouter les imports
`from ingestion.config import BREAST_CANCER_GENES, BRONZE, SICKLE_CELL_GENES` et
`from ingestion.storage import layer_uri, partition_uri` :

```python
_PANEL_GENES = {"brca": BREAST_CANCER_GENES, "sickle": SICKLE_CELL_GENES}


def _silver_table_uri(table: str, lake_uri: str | None) -> str:
    """URI d'une table Silver : `layer_uri` donne la racine de la couche
    (`file:///.../silver` ou `s3://silver`) ; une table Silver est un chemin direct
    en dessous, sans date ni panel (contrairement à `partition_uri`, conçue pour
    raw/bronze). Vérifié à la main : `layer_uri("silver", lake_uri=...)` fonctionne
    aussi bien en local qu'avec `lake_uri="s3://"`."""
    return f"{layer_uri('silver', lake_uri=lake_uri)}/{table}"


def bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Construit les neuf tables Silver du panel à partir du Bronze.

    Un seul appel par run de panel : lit les bronze partagés (`clinvar`, `hpo`,
    filtrés au panel) et les bronze du panel (`ncbi_gene`, `refseq`, `medgen`,
    `hpo_terms`). `clinvar_variant` seule porte un historique SCD2 ; les huit autres
    tables sont remplacées entièrement pour ce panel à chaque run.
    """
    genes = _PANEL_GENES[panel]

    clinvar_partition = partition_uri(BRONZE, "clinvar", logical_date, lake_uri=lake_uri)
    hpo_partition = partition_uri(BRONZE, "hpo", logical_date, lake_uri=lake_uri)
    ncbi_gene_partition = partition_uri(BRONZE, "ncbi_gene", logical_date, panel=panel, lake_uri=lake_uri)
    refseq_partition = partition_uri(BRONZE, "refseq", logical_date, panel=panel, lake_uri=lake_uri)
    medgen_partition = partition_uri(BRONZE, "medgen", logical_date, panel=panel, lake_uri=lake_uri)
    hpo_terms_partition = partition_uri(BRONZE, "hpo_terms", logical_date, panel=panel, lake_uri=lake_uri)

    silver_uri = lambda table: _silver_table_uri(table, lake_uri)

    variant_gene = _build_clinvar_variant_gene(clinvar_partition, genes)
    refseq_transcript = _build_refseq_transcript(refseq_partition)
    variant_rows = _build_clinvar_variant_rows(clinvar_partition, refseq_transcript, variant_gene)

    concept, mim, inheritance = _build_medgen_tables(medgen_partition)
    hpo_gene_phenotype = _build_hpo_gene_phenotype(hpo_partition, genes)
    hpo_term = _build_hpo_term(hpo_terms_partition)
    ncbi_gene = _build_ncbi_gene(ncbi_gene_partition)

    _write_clinvar_variant(
        variant_rows.with_columns(pl.lit(panel).alias("panel")),
        silver_uri("clinvar_variant"), panel, logical_date,
    )
    for table, df in [
        ("clinvar_variant_gene", variant_gene),
        ("ncbi_gene", ncbi_gene),
        ("refseq_transcript", refseq_transcript),
        ("medgen_concept", concept),
        ("medgen_mim", mim),
        ("medgen_inheritance", inheritance),
        ("hpo_gene_phenotype", hpo_gene_phenotype),
        ("hpo_term", hpo_term),
    ]:
        _write_silver_snapshot(df.with_columns(pl.lit(panel).alias("panel")), silver_uri(table), panel)
```

**Point d'attention — cohérence des URI de test.** Les tests des tâches précédentes
(Task 1 à 6) construisent l'URI d'une table Silver directement en chaîne
(`f"file://{tmp_path}/lake/silver/{table}"`). `_silver_table_uri` produit exactement
cette même forme (`layer_uri("silver", lake_uri=f"file://{tmp_path}/lake")` renvoie
`f"file://{tmp_path}/lake/silver"`) — les deux constructions sont interchangeables,
aucune divergence entre les tests déjà écrits et l'orchestration.

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_bronze_to_silver.py -q`
Expected: PASS, 25 passed

- [ ] **Step 5: Vérifier la suite complète**

Run: `venv/bin/pytest -q`
Expected: PASS, sans régression

- [ ] **Step 6: Commit**

```bash
git add src/transformations/bronze_to_silver.py tests/transformations/test_bronze_to_silver.py
git commit -m "feat: implement bronze_to_silver, orchestrating all nine Silver tables"
```

---

### Task 8 (C8) : `quality_check_silver` et câblage du DAG

**Files:**
- Create: `src/transformations/quality_check_silver.py`
- Create: `tests/transformations/test_quality_check_silver.py`
- Modify: `dags/dag_genomic_pipeline.py`

**Interfaces:**
- Consumes : `ingestion.config.{BREAST_CANCER_GENES, SICKLE_CELL_GENES}` ; `ingestion.storage.layer_uri` (ou l'équivalent tranché en Task 7 pour l'URI d'une table silver).
- Produces : `transformations.quality_check_silver.SilverQualityError(RuntimeError)` ; `transformations.quality_check_silver.quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None`.

- [ ] **Step 1: Écrire les tests (ils doivent échouer)**

Créer `tests/transformations/test_quality_check_silver.py` :

```python
import polars as pl
import pytest

from transformations.bronze_to_silver import _write_clinvar_variant, _write_silver_snapshot
from transformations.quality_check_silver import SilverQualityError, quality_check_silver

ALL_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "ncbi_gene", "refseq_transcript",
    "medgen_concept", "medgen_mim", "medgen_inheritance", "hpo_gene_phenotype", "hpo_term",
]


def _seed_complete_silver(lake, panel="brca"):
    uri = lambda table: f"{lake}/silver/{table}"
    _write_clinvar_variant(
        pl.DataFrame({
            "alleleid": ["1"], "panel": [panel], "clinicalsignificance": ["Benign"],
            "reviewstatus": ["criteria provided"], "lastevaluated": ["2026-08-01"],
        }),
        uri("clinvar_variant"), panel, "2026-08-01",
    )
    for table in ALL_TABLES:
        if table in ("clinvar_variant", "hpo_gene_phenotype"):
            continue
        _write_silver_snapshot(
            pl.DataFrame({"panel": [panel], "gene_symbol": ["BRCA1"]}), uri(table), panel
        )
    # hpo_gene_phenotype : vide légitime, mais présente (table créée).
    _write_silver_snapshot(
        pl.DataFrame({"panel": [], "gene_symbol": []}, schema={"panel": pl.Utf8, "gene_symbol": pl.Utf8}),
        uri("hpo_gene_phenotype"), panel,
    )
    _write_silver_snapshot(
        pl.DataFrame({"panel": [panel], "alleleid": ["1"], "gene_symbol": ["BRCA1"]}),
        uri("clinvar_variant_gene"), panel,
    )


def test_quality_check_silver_passes_on_a_complete_run(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)

    quality_check_silver("2026-09-01", "brca", lake_uri=lake)  # ne lève pas


def test_quality_check_silver_allows_an_empty_hpo_gene_phenotype(tmp_path):
    """HBS1L/MYB (sickle) n'ont légitimement aucune ligne dans hpo_gene_phenotype."""
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake, panel="sickle")

    quality_check_silver("2026-09-01", "sickle", lake_uri=lake)  # ne lève pas


def test_quality_check_silver_rejects_a_gene_outside_the_panel(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)
    _write_silver_snapshot(
        pl.DataFrame({"panel": ["brca"], "alleleid": ["2"], "gene_symbol": ["HBB"]}),
        f"{lake}/silver/clinvar_variant_gene", "brca",
    )

    with pytest.raises(SilverQualityError, match="clinvar_variant_gene"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_silver_rejects_two_current_rows_for_the_same_variant(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)
    import polars as pl
    pl.DataFrame({
        "alleleid": ["1"], "panel": ["brca"], "clinicalsignificance": ["Pathogenic"],
        "reviewstatus": ["criteria provided"], "lastevaluated": ["2026-09-01"],
        "valid_from": ["2026-09-01"], "valid_to": [None], "is_current": [True],
    }).write_delta(f"{lake}/silver/clinvar_variant", mode="append")

    with pytest.raises(SilverQualityError, match="clinvar_variant"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `venv/bin/pytest tests/transformations/test_quality_check_silver.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'transformations.quality_check_silver'`

- [ ] **Step 3: Implémenter**

Créer `src/transformations/quality_check_silver.py` :

```python
"""Contrôle qualité de la couche Silver : bloque la propagation vers le Gold en cas
d'échec, comme `assert_partitions_complete` le fait pour raw/bronze."""

from __future__ import annotations

import polars as pl

from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES
from ingestion.storage import layer_uri

_PANEL_GENES = {"brca": BREAST_CANCER_GENES, "sickle": SICKLE_CELL_GENES}

# hpo_gene_phenotype peut être vide (HBS1L, MYB : loci GWAS absents des annotations
# HPO) — déjà légitime en raw/bronze, ne pas le traiter comme un échec ici.
_TABLES_ALLOWED_EMPTY = {"hpo_gene_phenotype"}

_ALL_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "ncbi_gene", "refseq_transcript",
    "medgen_concept", "medgen_mim", "medgen_inheritance", "hpo_gene_phenotype", "hpo_term",
]


class SilverQualityError(RuntimeError):
    """Un ou plusieurs contrôles qualité Silver ont échoué."""


def quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Vérifie la complétude et la cohérence des neuf tables Silver pour ce panel.

    Toutes les erreurs sont rassemblées avant de lever, comme
    `assert_partitions_complete` le fait déjà pour raw/bronze — un message qui n'en
    citerait qu'une obligerait à relancer pour découvrir la suivante.
    """
    base = layer_uri("silver", lake_uri=lake_uri)
    errors: list[str] = []

    for table in _ALL_TABLES:
        df = pl.read_delta(f"{base}/{table}").filter(pl.col("panel") == panel)
        if len(df) == 0 and table not in _TABLES_ALLOWED_EMPTY:
            errors.append(f"{table} : aucune ligne pour le panel {panel!r}")

    variant_gene = pl.read_delta(f"{base}/clinvar_variant_gene").filter(pl.col("panel") == panel)
    unknown_genes = set(variant_gene["gene_symbol"].to_list()) - set(_PANEL_GENES[panel])
    if unknown_genes:
        errors.append(
            f"clinvar_variant_gene : gènes hors panel {panel!r} : {sorted(unknown_genes)}"
        )

    variant = pl.read_delta(f"{base}/clinvar_variant").filter(
        (pl.col("panel") == panel) & pl.col("is_current")
    )
    duplicated = (
        variant.group_by("alleleid").agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    )
    if len(duplicated) > 0:
        errors.append(
            f"clinvar_variant : plusieurs lignes is_current pour "
            f"{duplicated['alleleid'].to_list()}"
        )

    if errors:
        raise SilverQualityError("; ".join(errors))
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `venv/bin/pytest tests/transformations/test_quality_check_silver.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Câbler la vraie fonction dans le DAG**

Dans `dags/dag_genomic_pipeline.py` :

Remplacer :
```python
from transformations.bronze_to_silver import bronze_to_silver
from transformations import SPEC
from transformations.raw_to_bronze import raw_to_bronze
```
par :
```python
from transformations.bronze_to_silver import bronze_to_silver
from transformations.quality_check_silver import quality_check_silver
from transformations.raw_to_bronze import raw_to_bronze
```

(`SPEC` disparaît de cet import : vérifié — après les deux remplacements suivants, `SPEC`
n'est plus référencé nulle part ailleurs dans ce fichier, `grep -n SPEC
dags/dag_genomic_pipeline.py` ne doit plus rien trouver.)

Remplacer :
```python
        @task(task_id="quality_check_silver")
        def task_quality_check_silver() -> None:
            raise NotImplementedError(
                f"quality_check_silver : implémenté par le sous-projet C ({SPEC}, §7)"
            )
```
par :
```python
        @task(task_id="quality_check_silver")
        def task_quality_check_silver(sources_date: str) -> None:
            quality_check_silver(sources_date, panel)
```

Remplacer :
```python
        quality = task_quality_check_silver()
```
par :
```python
        quality = task_quality_check_silver(sources_date)
```

Note : avant ce plan, `SPEC` n'était utilisé dans ce fichier que par le message
d'erreur retiré ci-dessus (vérifié : `grep -n SPEC dags/dag_genomic_pipeline.py` ne
trouvait que l'import et cette seule ligne) — son retrait de l'import ci-dessus est
donc définitif, pas une supposition à revérifier.

- [ ] **Step 6: Vérifier les deux passes**

Run: `venv/bin/pytest tests_airflow -q && venv/bin/pytest -q`
Expected: `tests_airflow` toujours au même nombre de tests qu'avant ce plan (aucune
assertion sur le comportement de `quality_check_silver`, seulement sa présence dans le
graphe) ; passe rapide sans régression.

- [ ] **Step 7: Commit**

```bash
git add src/transformations/quality_check_silver.py tests/transformations/test_quality_check_silver.py dags/dag_genomic_pipeline.py
git commit -m "feat: implement quality_check_silver and wire it into the panel DAG"
```

---

### Task 9 (C9) : Vérification finale

**Files:** aucun changement de code.

- [ ] **Step 1: Passe rapide complète, avec mesure du temps**

Run: `time venv/bin/pytest -q`
Expected: PASS, sans régression, sous ~3 s. Si l'écriture Delta locale pousse la suite
au-delà (I/O du journal de transactions Delta par test), envisager de regrouper les
écritures Delta dans moins de fichiers `tmp_path` distincts plutôt que d'accepter une
suite lente — mais vérifier d'abord le temps réel avant de changer quoi que ce soit.

- [ ] **Step 2: Passe Airflow**

Run: `venv/bin/pytest tests_airflow -q`
Expected: PASS, sans régression.

- [ ] **Step 3: Aucun moteur interdit importé**

Run: `grep -rnE "^(import|from) (pyspark|pandas|pyarrow)" src/transformations/ || echo "aucun moteur interdit importe"`
Expected: `aucun moteur interdit importe`

- [ ] **Step 4: Mettre à jour CLAUDE.md**

Dans `CLAUDE.md`, section « Orchestration — Airflow 3 », remplacer :
```markdown
- `src/transformations/` contient les passages entre couches : `raw_to_bronze` livré
  (sous-projet B), `bronze_to_silver`/`silver_to_gold_rag`/`silver_to_gold_analytique`
  restent des stubs (sous-projets C et D).
```
par :
```markdown
- `src/transformations/` contient les passages entre couches : `raw_to_bronze`
  (sous-projet B) et `bronze_to_silver`/`quality_check_silver` (sous-projet C) livrés ;
  `silver_to_gold_rag`/`silver_to_gold_analytique` restent des stubs (sous-projet D).
```

**Note** : au moment d'exécuter ce plan, `raw_to_bronze` peut être encore un stub sur
la branche courante (livré sur une branche séparée, pas encore fusionnée) — si c'est le
cas, adapter cette phrase pour refléter l'état réel plutôt que de copier ce texte tel
quel.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark bronze_to_silver and quality_check_silver as delivered in CLAUDE.md"
```
