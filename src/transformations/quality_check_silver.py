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
