"""Contrôle qualité de la couche Silver : bloque la propagation vers le Gold en cas
d'échec, comme `assert_partitions_complete` le fait pour raw/bronze."""

from __future__ import annotations

import polars as pl
from deltalake.exceptions import TableNotFoundError

from ingestion.config import PANEL_GENES, SILVER_TABLES
from ingestion.storage import layer_uri, storage_options

# hpo_gene_phenotype peut être vide (HBS1L, MYB : loci GWAS absents des annotations
# HPO) — déjà légitime en raw/bronze, ne pas le traiter comme un échec ici.
_TABLES_ALLOWED_EMPTY = {"hpo_gene_phenotype"}


class SilverQualityError(RuntimeError):
    """Un ou plusieurs contrôles qualité Silver ont échoué."""


def _read_silver(base: str, table: str) -> pl.DataFrame:
    uri = f"{base}/{table}"
    return pl.read_delta(uri, storage_options=storage_options(uri))


def quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Vérifie la complétude et la cohérence des neuf tables Silver pour ce panel.

    Toutes les erreurs sont rassemblées avant de lever, comme
    `assert_partitions_complete` le fait déjà pour raw/bronze — un message qui n'en
    citerait qu'une obligerait à relancer pour découvrir la suivante.
    """
    base = layer_uri("silver", lake_uri=lake_uri)
    errors: list[str] = []

    for table in SILVER_TABLES:
        try:
            df = _read_silver(base, table).filter(pl.col("panel") == panel)
        except TableNotFoundError:
            errors.append(f"{table} : table absente")
            continue
        if len(df) == 0 and table not in _TABLES_ALLOWED_EMPTY:
            errors.append(f"{table} : aucune ligne pour le panel {panel!r}")

    variant_gene = _read_silver(base, "clinvar_variant_gene").filter(pl.col("panel") == panel)
    unknown_genes = set(variant_gene["gene_symbol"].to_list()) - set(PANEL_GENES[panel])
    if unknown_genes:
        errors.append(
            f"clinvar_variant_gene : gènes hors panel {panel!r} : {sorted(unknown_genes)}"
        )

    variant = _read_silver(base, "clinvar_variant").filter(
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

    # Intégrité référentielle C4 : tout alleleid présent dans clinvar_variant_gene
    # (la table qui décide l'appartenance au panel) doit avoir une ligne
    # correspondante dans clinvar_variant (courante ou historique), sans quoi une
    # jointure en aval produirait une référence pendante.
    known_alleleids = set(
        _read_silver(base, "clinvar_variant").filter(pl.col("panel") == panel)["alleleid"].to_list()
    )
    dangling = set(variant_gene["alleleid"].to_list()) - known_alleleids
    if dangling:
        errors.append(
            f"clinvar_variant_gene : alleleid sans ligne correspondante dans clinvar_variant : "
            f"{sorted(dangling)}"
        )

    if errors:
        raise SilverQualityError("; ".join(errors))
