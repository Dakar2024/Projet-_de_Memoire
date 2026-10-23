"""Passage bronze → silver : dix tables Delta typées, historique SCD2 sur `clinvar_variant`."""
from __future__ import annotations

import io
import json
import re

import polars as pl
from deltalake import DeltaTable

from ingestion.config import BRONZE, PANEL_GENES
from ingestion.errors import OutOfOrderMonthError
from ingestion.medgen import parse_medgen_conceptmeta
from ingestion.storage import get_bytes, partition_uri, scan_parquet, storage_options
from transformations.silver_io import silver_table_uri

# Colonnes techniques bronze, jamais propagées en Silver.
_BRONZE_TECHNICAL_COLUMNS = ["_source_version", "_logical_date", "_ingested_at"]


def _read_bronze_table(bronze_partition: str) -> pl.DataFrame:
    """Lit le `data.parquet` d'une partition bronze, sans ses colonnes techniques."""
    df = pl.read_parquet(io.BytesIO(get_bytes(f"{bronze_partition}/data.parquet")))
    return df.drop(_BRONZE_TECHNICAL_COLUMNS, strict=False)


def _write_silver_snapshot(df: pl.DataFrame, table_uri: str, panel: str) -> None:
    """Remplace les lignes du seul panel courant dans une table Silver sans historique."""
    df.write_delta(
        table_uri,
        mode="overwrite",
        storage_options=storage_options(table_uri),
        delta_write_options={"partition_by": ["panel"], "predicate": f"panel = '{panel}'"},
    )


def _load_clinvar_variants(bronze_partition: str, genes: list[str]) -> pl.DataFrame:
    """Lit les variants ClinVar GRCh38 du panel, dédoublonnés par `alleleid` (source commune des tables variant)."""
    grch38 = (
        scan_parquet(f"{bronze_partition}/data.parquet")
        .drop(_BRONZE_TECHNICAL_COLUMNS, strict=False)
        .filter(pl.col("assembly") == "GRCh38")
    )
    # Filtre au panel avant `.collect()` : tout le ClinVar GRCh38 en mémoire tue le worker (OOM).
    panel_ids = (
        grch38.select("alleleid", pl.col("genesymbol").str.split(";").alias("gene_symbol"))
        .explode("gene_symbol", empty_as_null=True)
        .filter(pl.col("gene_symbol").is_in(genes))
        .select("alleleid")
        .unique()
        .collect()["alleleid"]
        .to_list()
    )
    return (
        grch38.filter(pl.col("alleleid").is_in(panel_ids))
        .unique(subset=["alleleid"], keep="first", maintain_order=True)
        .collect()
    )


def _build_clinvar_variant_gene(clinvar_variants: pl.DataFrame, genes: list[str]) -> pl.DataFrame:
    """Éclate `genesymbol` (gènes joints par `;`) et garde le panel : cette table définit les variants du panel."""
    exploded = (
        clinvar_variants.select(["alleleid", "genesymbol"])
        .with_columns(pl.col("genesymbol").str.split(";").alias("gene_symbol"))
        .explode("gene_symbol")
        .drop("genesymbol")
    )
    return exploded.filter(pl.col("gene_symbol").is_in(genes))


# Identifiants de maladie portés par `phenotypeids` (MedGen accepte aussi la forme `CN123`).
_DISEASE_ID_PATTERNS = {
    "medgen_cui": r"MedGen:(CN?\d+)",
    "omim_id": r"OMIM:(\d+)",
    "orpha_id": r"Orphanet:(\d+)",
    "mondo_id": r"MONDO:(MONDO:\d+)",
}

# Libellés « sans maladie » de ClinVar ; ils ont leur propre CUI, d'où un filtre sur le nom.
_PLACEHOLDER_DISEASE_NAMES = ["not provided", "not specified"]


def _build_clinvar_variant_disease(clinvar_variants: pl.DataFrame) -> pl.DataFrame:
    """Éclate `phenotypelist`/`phenotypeids` en une ligne par (variant, maladie) ; nom nul si désalignés."""
    groups = (
        clinvar_variants.select(
            "alleleid",
            pl.col("phenotypelist").str.split("|").alias("group_names"),
            pl.col("phenotypeids").str.split("|").alias("group_ids"),
        )
        .filter(pl.col("group_names").list.len() == pl.col("group_ids").list.len())
        .explode("group_names", "group_ids")
        .with_columns(
            pl.col("group_names").str.split(";").alias("names"),
            pl.col("group_ids").str.split(";").alias("ids"),
        )
    )
    same_length = pl.col("names").list.len() == pl.col("ids").list.len()
    aligned = groups.filter(same_length).explode("names", "ids")
    misaligned = (
        groups.filter(~same_length)
        .explode("ids")
        .with_columns(pl.lit(None, dtype=pl.Utf8).alias("names"))
    )

    rows = pl.concat([
        aligned.select("alleleid", "names", "ids"),
        misaligned.select("alleleid", "names", "ids"),
    ]).with_columns(
        pl.col("names").str.strip_chars().alias("disease_name"),
        *[
            pl.col("ids").str.extract(pattern, 1).alias(column)
            for column, pattern in _DISEASE_ID_PATTERNS.items()
        ],
    )

    without_id = pl.all_horizontal(
        [pl.col(column).is_null() for column in _DISEASE_ID_PATTERNS]
    )
    placeholder = pl.col("disease_name").str.to_lowercase().is_in(_PLACEHOLDER_DISEASE_NAMES)
    return (
        rows.filter(~placeholder.fill_null(False) & ~(without_id & pl.col("disease_name").is_null()))
        .select("alleleid", "disease_name", *_DISEASE_ID_PATTERNS)
        .unique(subset=["alleleid", "disease_name", "medgen_cui"], keep="first")
    )


# `NM_014855.3(AP5Z1):c.80_83delinsTGCTG (p.X)` → accession, version, HGVS c. et p. (optionnel).
_HGVS_PATTERN = re.compile(
    r"^(?P<accession>[A-Z]+_\d+)\.(?P<version>\d+)\([^)]+\):(?P<hgvs_c>[^\s(]+)"
    r"(?:\s*\((?P<hgvs_p>p\.[^)]+)\))?"
)


def _parse_hgvs(name: str) -> dict:
    """Extrait accession, version et HGVS d'un nom ClinVar ; champs nuls s'il n'est pas reconnu."""
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
    clinvar_variants: pl.DataFrame, refseq_df: pl.DataFrame, variant_gene: pl.DataFrame
) -> pl.DataFrame:
    """Construit une ligne par variant du panel, HGVS parsé et validé contre RefSeq (SCD2 ajouté à l'écriture)."""
    panel_ids = variant_gene["alleleid"].unique().to_list()

    filtered = (
        clinvar_variants.filter(pl.col("alleleid").is_in(panel_ids))
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
    # `fill_null(False)` : un HGVS non reconnu vaut `False`, pas `null`.
    hgvs_df = hgvs_df.with_columns(
        pl.col("refseq_accession")
        .is_in(known_accessions)
        .fill_null(False)
        .alias("refseq_accession_known")
    )

    return filtered.join(hgvs_df, on="alleleid")


def _build_ncbi_gene(bronze_partition: str) -> pl.DataFrame:
    """Extrait les champs connus d'`esummary_json` ; un gène non résolu garde sa ligne, champs nuls."""
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
    # Schéma explicite : une colonne entièrement nulle serait typée `Null`, refusé par Delta.
    return pl.DataFrame(
        rows,
        schema={
            "gene_symbol": pl.Utf8, "name": pl.Utf8, "description": pl.Utf8,
            "maplocation": pl.Utf8, "summary": pl.Utf8,
        },
    )


def _build_refseq_transcript(bronze_partition: str) -> pl.DataFrame:
    """Éclate `transcripts_json` en une ligne par transcrit (`NM_007294.4` → accession + version)."""
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


def _build_medgen_tables(bronze_partition: str) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Construit `medgen_concept`, `medgen_mim` et `medgen_inheritance` depuis le `conceptmeta`."""
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

    # Schéma explicite : un CUI non résolu laisse des colonnes entièrement nulles.
    return (
        pl.DataFrame(
            concept_rows,
            schema={
                "cui": pl.Utf8, "conceptmeta_xml": pl.Utf8, "mim_number": pl.Utf8,
                "mode_inheritance": pl.Utf8, "clinical_summary": pl.Utf8,
            },
        ),
        pl.DataFrame(mim_rows, schema={"cui": pl.Utf8, "mim_number": pl.Utf8}),
        pl.DataFrame(inheritance_rows, schema={"cui": pl.Utf8, "mode_inheritance": pl.Utf8}),
    )


def _build_hpo_gene_phenotype(bronze_partition: str, genes: list[str]) -> pl.DataFrame:
    """Garde les lignes HPO des gènes du panel (vide pour HBS1L et MYB, c'est attendu)."""
    df = _read_bronze_table(bronze_partition)
    return df.filter(pl.col("gene_symbol").is_in(genes))


def _build_hpo_term(bronze_partition: str) -> pl.DataFrame:
    """Extrait definition/synonyms/xrefs de `details_json` ; un terme retiré garde sa ligne."""
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
    # Schéma explicite : des listes toutes vides seraient typées `List(Null)`, refusé par Delta.
    return pl.DataFrame(
        rows,
        schema={
            "gene_symbol": pl.Utf8, "hpo_id": pl.Utf8, "hpo_name": pl.Utf8,
            "definition": pl.Utf8, "synonyms": pl.List(pl.Utf8), "xrefs": pl.List(pl.Utf8),
        },
    )


# Seuls ces champs (reclassification) créent une nouvelle version SCD2.
_CLINVAR_WATCHED_FIELDS = ["clinicalsignificance", "reviewstatus", "lastevaluated"]


def _check_month_order(table_uri: str, panel: str, logical_date: str) -> None:
    """Refuse un mois antérieur au plus récent `valid_from` du panel ; le même mois reste rejouable.

    La fusion SCD2 compare toujours aux lignes courantes : un mois ancien rejoué après un plus
    récent fermerait les versions récentes avant leur début et rendrait l'état ancien courant.
    """
    if not DeltaTable.is_deltatable(table_uri, storage_options=storage_options(table_uri)):
        return
    latest = (
        pl.read_delta(table_uri, columns=["panel", "valid_from"], storage_options=storage_options(table_uri))
        .filter(pl.col("panel") == panel)["valid_from"]
        .max()
    )
    if latest is not None and logical_date < latest:
        raise OutOfOrderMonthError(
            f"clinvar_variant ({panel}) contient déjà le mois {latest} : y ajouter {logical_date} "
            "après lui fausserait l'historique SCD2 (voir reference/procedure_reprise.md)"
        )


def _write_clinvar_variant(
    rows: pl.DataFrame, table_uri: str, panel: str, logical_date: str
) -> None:
    """Écrit `clinvar_variant` en SCD2 (création, sinon MERGE) ; `rows` porte déjà `panel`, rejeu idempotent."""
    if not DeltaTable.is_deltatable(table_uri, storage_options=storage_options(table_uri)):
        initial = rows.with_columns([
            pl.lit(logical_date).alias("valid_from"),
            pl.lit(None, dtype=pl.Utf8).alias("valid_to"),
            pl.lit(True).alias("is_current"),
        ])
        initial.write_delta(
            table_uri,
            mode="overwrite",
            storage_options=storage_options(table_uri),
            delta_write_options={"partition_by": ["panel"]},
        )
        return

    current = pl.read_delta(table_uri, storage_options=storage_options(table_uri)).filter(
        pl.col("is_current") & (pl.col("panel") == panel)
    )
    current_ids = current["alleleid"].to_list()

    # `_matched_current` distingue « sans correspondance » d'un champ surveillé réellement nul.
    current_watched = (
        current.select(["alleleid"] + _CLINVAR_WATCHED_FIELDS)
        .rename({f: f"cur_{f}" for f in _CLINVAR_WATCHED_FIELDS})
        .with_columns(pl.lit(True).alias("_matched_current"))
    )
    joined = rows.join(current_watched, on="alleleid", how="left")
    # `ne_missing` et non `!=` : détecte aussi la transition `null → valeur`.
    changed = pl.any_horizontal(
        [pl.col(f).ne_missing(pl.col(f"cur_{f}")) for f in _CLINVAR_WATCHED_FIELDS]
    ) | pl.col("_matched_current").is_null()
    to_process = joined.filter(changed).drop(
        [f"cur_{f}" for f in _CLINVAR_WATCHED_FIELDS] + ["_matched_current"]
    )

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
        storage_options=storage_options(table_uri),
        delta_merge_options={
            "predicate": (
                "target.alleleid = source.merge_key AND target.panel = source.panel "
                "AND target.is_current = true"
            ),
            "source_alias": "source",
            "target_alias": "target",
        },
    )
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


def bronze_to_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Construit les dix tables Silver du panel ; seule `clinvar_variant` garde un historique (SCD2)."""
    genes = PANEL_GENES[panel]
    # Avant toute écriture : les neuf instantanés reviendraient eux aussi au mois ancien.
    _check_month_order(silver_table_uri("clinvar_variant", lake_uri), panel, logical_date)

    clinvar_partition = partition_uri(BRONZE, "clinvar", logical_date, lake_uri=lake_uri)
    hpo_partition = partition_uri(BRONZE, "hpo", logical_date, lake_uri=lake_uri)
    ncbi_gene_partition = partition_uri(BRONZE, "ncbi_gene", logical_date, panel=panel, lake_uri=lake_uri)
    refseq_partition = partition_uri(BRONZE, "refseq", logical_date, panel=panel, lake_uri=lake_uri)
    medgen_partition = partition_uri(BRONZE, "medgen", logical_date, panel=panel, lake_uri=lake_uri)
    hpo_terms_partition = partition_uri(BRONZE, "hpo_terms", logical_date, panel=panel, lake_uri=lake_uri)

    clinvar_variants = _load_clinvar_variants(clinvar_partition, genes)
    variant_gene = _build_clinvar_variant_gene(clinvar_variants, genes)
    variant_disease = _build_clinvar_variant_disease(
        clinvar_variants.filter(pl.col("alleleid").is_in(variant_gene["alleleid"].unique().to_list()))
    )
    refseq_transcript = _build_refseq_transcript(refseq_partition)
    variant_rows = _build_clinvar_variant_rows(clinvar_variants, refseq_transcript, variant_gene)

    concept, mim, inheritance = _build_medgen_tables(medgen_partition)
    hpo_gene_phenotype = _build_hpo_gene_phenotype(hpo_partition, genes)
    hpo_term = _build_hpo_term(hpo_terms_partition)
    ncbi_gene = _build_ncbi_gene(ncbi_gene_partition)

    _write_clinvar_variant(
        variant_rows.with_columns(pl.lit(panel).alias("panel")),
        silver_table_uri("clinvar_variant", lake_uri), panel, logical_date,
    )
    for table, df in [
        ("clinvar_variant_disease", variant_disease),
        ("clinvar_variant_gene", variant_gene),
        ("ncbi_gene", ncbi_gene),
        ("refseq_transcript", refseq_transcript),
        ("medgen_concept", concept),
        ("medgen_mim", mim),
        ("medgen_inheritance", inheritance),
        ("hpo_gene_phenotype", hpo_gene_phenotype),
        ("hpo_term", hpo_term),
    ]:
        _write_silver_snapshot(
            df.with_columns(pl.lit(panel).alias("panel")), silver_table_uri(table, lake_uri), panel
        )
