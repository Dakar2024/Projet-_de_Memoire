"""Passage bronze -> silver : neuf tables Delta typées, historique SCD2 sur
`clinvar_variant`. Voir docs/superpowers/specs/2026-09-16-sous-projet-c-bronze-silver-design.md.
"""

from __future__ import annotations

import io
import re

import polars as pl

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
