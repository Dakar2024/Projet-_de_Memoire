"""Contrôle qualité de la couche Silver : bloque la propagation vers le Gold en cas
d'échec, comme `assert_partitions_complete` le fait pour raw/bronze."""

from __future__ import annotations

import polars as pl
from deltalake.exceptions import TableNotFoundError

from ingestion.config import PANEL_GENES, SILVER_TABLES
from transformations.silver_io import read_silver

# hpo_gene_phenotype peut être vide (HBS1L, MYB : loci GWAS absents des annotations
# HPO) — déjà légitime en raw/bronze, ne pas le traiter comme un échec ici.
_TABLES_ALLOWED_EMPTY = {"hpo_gene_phenotype"}

# Proportion maximale de variants encore `is_current` mais absents de l'instantané
# du mois. ClinVar en retire quelques-uns d'un mois sur l'autre : c'est normal. Une
# proportion massive ne l'est pas — elle signale une archive tronquée ou une
# conversion partielle. Le seuil vaut parce que le `MERGE` SCD2 ne clôture jamais un
# variant absent du nouveau lot : sans ce contrôle, `clinvar_variant` conserverait
# des variants périmés pendant que les tables instantanées rétréciraient, et tous
# les autres contrôles resteraient verts.
MAX_RETIRED_VARIANT_RATIO = 0.05


class SilverQualityError(RuntimeError):
    """Un ou plusieurs contrôles qualité Silver ont échoué."""


def quality_check_silver(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Vérifie la complétude et la cohérence des neuf tables Silver pour ce panel.

    Toutes les erreurs sont rassemblées avant de lever, comme
    `assert_partitions_complete` le fait déjà pour raw/bronze — un message qui n'en
    citerait qu'une obligerait à relancer pour découvrir la suivante.
    """
    errors: list[str] = []

    for table in SILVER_TABLES:
        try:
            df = read_silver(table, panel, lake_uri=lake_uri)
        except TableNotFoundError:
            errors.append(f"{table} : table absente")
            continue
        if len(df) == 0 and table not in _TABLES_ALLOWED_EMPTY:
            errors.append(f"{table} : aucune ligne pour le panel {panel!r}")

    variant_gene = read_silver("clinvar_variant_gene", panel, lake_uri=lake_uri)
    unknown_genes = set(variant_gene["gene_symbol"].to_list()) - set(PANEL_GENES[panel])
    if unknown_genes:
        errors.append(
            f"clinvar_variant_gene : gènes hors panel {panel!r} : {sorted(unknown_genes)}"
        )

    variant = read_silver("clinvar_variant", panel, lake_uri=lake_uri).filter(pl.col("is_current"))
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
        read_silver("clinvar_variant", panel, lake_uri=lake_uri)["alleleid"].to_list()
    )
    dangling = set(variant_gene["alleleid"].to_list()) - known_alleleids
    if dangling:
        errors.append(
            f"clinvar_variant_gene : alleleid sans ligne correspondante dans clinvar_variant : "
            f"{sorted(dangling)}"
        )

    variant_disease = read_silver("clinvar_variant_disease", panel, lake_uri=lake_uri)
    dangling_disease = set(variant_disease["alleleid"].to_list()) - set(
        variant["alleleid"].to_list()
    )
    if dangling_disease:
        errors.append(
            f"clinvar_variant_disease : alleleid sans ligne correspondante dans "
            f"clinvar_variant : {sorted(dangling_disease)}"
        )

    # Plausibilité d'un mois sur l'autre : les variants encore courants que
    # l'instantané du mois ne mentionne plus. `variant` ne contient que les lignes
    # courantes du panel, `variant_gene` est réécrit intégralement à chaque run.
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

    if errors:
        raise SilverQualityError("; ".join(errors))
