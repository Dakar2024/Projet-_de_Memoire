"""Contrôle qualité de la couche Silver : avant sa publication (dans `bronze_to_silver`), puis avant le Gold."""
from __future__ import annotations

from collections.abc import Mapping

import polars as pl
from deltalake.exceptions import TableNotFoundError

from ingestion.config import PANEL_GENES, SILVER_TABLES
from transformations.silver_io import read_silver

# Vide légitimement pour HBS1L et MYB (loci GWAS absents de HPO).
_TABLES_ALLOWED_EMPTY = {"hpo_gene_phenotype"}

# Au-delà de 5 % de variants courants absents du mois, l'archive est probablement tronquée.
MAX_RETIRED_VARIANT_RATIO = 0.05


class SilverQualityError(RuntimeError):
    """Un ou plusieurs contrôles qualité Silver ont échoué."""


def find_silver_errors(tables: Mapping[str, pl.DataFrame | None], panel: str) -> list[str]:
    """Contrôles de complétude et de cohérence, sur les tables du panel telles qu'elles sont ou seront publiées.

    `tables` : chaque table Silver, `None` si absente ; `clinvar_variant` porte au moins `alleleid`
    et `is_current`. Pur : `bronze_to_silver` l'applique aux tables candidates avant d'écrire,
    `quality_check_silver` aux tables publiées.
    """
    errors: list[str] = []
    for table in SILVER_TABLES:
        df = tables.get(table)
        if df is None:
            errors.append(f"{table} : table absente")
        elif len(df) == 0 and table not in _TABLES_ALLOWED_EMPTY:
            errors.append(f"{table} : aucune ligne pour le panel {panel!r}")

    all_variants = tables.get("clinvar_variant")
    variant_gene = tables.get("clinvar_variant_gene")
    variant_disease = tables.get("clinvar_variant_disease")
    if all_variants is None or variant_gene is None or variant_disease is None:
        return errors

    unknown_genes = set(variant_gene["gene_symbol"].to_list()) - set(PANEL_GENES[panel])
    if unknown_genes:
        errors.append(
            f"clinvar_variant_gene : gènes hors panel {panel!r} : {sorted(unknown_genes)}"
        )

    variant = all_variants.filter(pl.col("is_current"))
    duplicated = (
        variant.group_by("alleleid").agg(pl.len().alias("n")).filter(pl.col("n") > 1)
    )
    if len(duplicated) > 0:
        errors.append(
            f"clinvar_variant : plusieurs lignes is_current pour "
            f"{duplicated['alleleid'].to_list()}"
        )

    # Intégrité référentielle : chaque variant du panel existe dans clinvar_variant.
    dangling = set(variant_gene["alleleid"].to_list()) - set(all_variants["alleleid"].to_list())
    if dangling:
        errors.append(
            f"clinvar_variant_gene : alleleid sans ligne correspondante dans clinvar_variant : "
            f"{sorted(dangling)}"
        )

    dangling_disease = set(variant_disease["alleleid"].to_list()) - set(
        variant["alleleid"].to_list()
    )
    if dangling_disease:
        errors.append(
            f"clinvar_variant_disease : alleleid sans ligne correspondante dans "
            f"clinvar_variant : {sorted(dangling_disease)}"
        )

    # Plausibilité d'un mois à l'autre : variants courants absents de l'instantané du mois.
    courants = set(variant["alleleid"].to_list())
    if courants:
        retires = courants - set(variant_gene["alleleid"].to_list())
        proportion = len(retires) / len(courants)
        if proportion > MAX_RETIRED_VARIANT_RATIO:
            errors.append(
                f"clinvar_variant : {len(retires)} variant(s) courant(s) sur {len(courants)} "
                f"absent(s) de l'instantané du mois, soit {proportion:.0%} — au-delà du seuil "
                f"de {MAX_RETIRED_VARIANT_RATIO:.0%}, cela signale une archive ClinVar "
                f"tronquée ou une conversion partielle, pas des retraits ordinaires"
            )
    return errors


def _read_or_none(table: str, panel: str, lake_uri: str | None) -> pl.DataFrame | None:
    try:
        return read_silver(table, panel, lake_uri=lake_uri)
    except TableNotFoundError:
        return None


def quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Revérifie les tables Silver publiées du panel, en levant toutes les erreurs à la fois.

    `bronze_to_silver` a déjà contrôlé ses tables avant de les écrire ; ce contrôle-ci attrape ce
    que l'écriture elle-même aurait cassé (écriture interrompue entre deux tables).
    """
    tables = {table: _read_or_none(table, panel, lake_uri) for table in SILVER_TABLES}
    errors = find_silver_errors(tables, panel)
    if errors:
        raise SilverQualityError("; ".join(errors))
