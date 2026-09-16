"""Passage bronze -> silver : neuf tables Delta typées, historique SCD2 sur
`clinvar_variant`. Voir docs/superpowers/specs/2026-09-16-sous-projet-c-bronze-silver-design.md.
"""

from __future__ import annotations

import io
import json
import re

import polars as pl
from deltalake import DeltaTable

from ingestion.medgen import parse_medgen_conceptmeta
from ingestion.storage import get_bytes
from transformations import SPEC


# Jamais propagées dans une table Silver (contrainte globale de ce plan) : aucun
# bâtisseur n'en a besoin, retirées une bonne fois ici plutôt que dans chacun.
# `strict=False` : les fixtures de test, minimales, ne les incluent pas toujours —
# ce n'est pas une erreur de les retirer quand elles sont déjà absentes.
_BRONZE_TECHNICAL_COLUMNS = ["_source_version", "_logical_date", "_ingested_at"]


def _read_bronze_table(bronze_partition: str) -> pl.DataFrame:
    """Relit le Parquet d'une partition bronze (fichier unique `data.parquet`),
    sans ses colonnes techniques (`_source_version`/`_logical_date`/`_ingested_at`)."""
    df = pl.read_parquet(io.BytesIO(get_bytes(f"{bronze_partition}/data.parquet")))
    return df.drop(_BRONZE_TECHNICAL_COLUMNS, strict=False)


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
    # `.to_list()` : `is_in` avec une Series du même dtype est ambigu et dépréciée
    # côté Polars (avertissement, comportement inchangé) — une liste lève l'ambiguïté.
    panel_ids = variant_gene["alleleid"].unique().to_list()

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
    # `is_in` propage le null d'une accession non parsée au lieu de le traiter comme
    # "absente" : `fill_null(False)` pour qu'un HGVS non reconnu reste `False`, pas `null`.
    hgvs_df = hgvs_df.with_columns(
        pl.col("refseq_accession")
        .is_in(known_accessions)
        .fill_null(False)
        .alias("refseq_accession_known")
    )

    return filtered.join(hgvs_df, on="alleleid")


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
