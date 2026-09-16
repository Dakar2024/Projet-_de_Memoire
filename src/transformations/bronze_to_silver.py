"""Passage bronze -> silver : neuf tables Delta typées, historique SCD2 sur
`clinvar_variant`. Voir docs/superpowers/specs/2026-09-16-sous-projet-c-bronze-silver-design.md.
"""

from __future__ import annotations

import io

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
