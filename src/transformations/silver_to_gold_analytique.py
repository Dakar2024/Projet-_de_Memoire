"""Passage silver → gold analytique : modèle en étoile et agrégats, lus par DuckDB pour l'application."""
from __future__ import annotations

import polars as pl

from ingestion.storage import layer_uri, storage_options
from transformations.silver_io import read_silver

# Étoiles ClinVar par statut de revue ; « - » (aucun statut) absent exprès, donc nul.
_REVIEW_STATUS_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, single submitter": 1,
    "criteria provided, conflicting classifications": 1,
    "no assertion criteria provided": 0,
    "no assertion provided": 0,
    "no classification provided": 0,
    "no classification for the single variant": 0,
    "no classifications from unflagged records": 0,
}


def gold_table_uri(table: str, lake_uri: str | None = None) -> str:
    """Renvoie l'URI d'une table de `gold/analytique`."""
    return f"{layer_uri('gold', lake_uri=lake_uri)}/analytique/{table}"


def build_fact_variant(
    variants: pl.DataFrame, variant_gene: pl.DataFrame, month: str
) -> pl.DataFrame:
    """Construit une ligne par (variant courant, gène du panel)."""
    return (
        variants.filter(pl.col("is_current"))
        .join(variant_gene.select("alleleid", "gene_symbol"), on="alleleid", how="left")
        .select(
            "alleleid",
            "gene_symbol",
            pl.col("clinicalsignificance").alias("clinical_significance"),
            pl.col("clinsigsimple").alias("clinsig_simple"),
            pl.col("reviewstatus").alias("review_status"),
            "chromosome",
            pl.col("type").alias("variant_type"),
            "panel",
            pl.lit(month).alias("month"),
        )
    )


def build_fact_variant_disease(
    variant_disease: pl.DataFrame, variant_gene: pl.DataFrame, month: str
) -> pl.DataFrame:
    """Construit le pont variant × maladie, pour compter par maladie sans surcompter `fact_variant`."""
    return (
        variant_disease.join(
            variant_gene.select("alleleid", "gene_symbol"), on="alleleid", how="left"
        )
        .select("alleleid", "medgen_cui", "disease_name", "gene_symbol", "panel",
                pl.lit(month).alias("month"))
    )


def build_fact_reclassification(
    variants: pl.DataFrame, variant_gene: pl.DataFrame
) -> pl.DataFrame:
    """Construit une ligne par transition SCD2, en appariant chaque version clôturée à la suivante."""
    closed = variants.filter(pl.col("valid_to").is_not_null())
    return (
        closed.join(
            variants.select(
                "alleleid", "panel",
                pl.col("valid_from").alias("valid_to"),
                pl.col("clinicalsignificance").alias("significance_to"),
                pl.col("reviewstatus").alias("review_status_to"),
            ),
            on=["alleleid", "panel", "valid_to"],
            how="inner",
        )
        .join(variant_gene.select("alleleid", "gene_symbol"), on="alleleid", how="left")
        .select(
            "alleleid",
            "gene_symbol",
            pl.col("clinicalsignificance").alias("significance_from"),
            "significance_to",
            "review_status_to",
            pl.col("valid_to").alias("changed_on"),
            "panel",
        )
    )


def _month_row(month: str) -> dict:
    """Construit la ligne de `dim_month` d'un mois `YYYY-MM`."""
    year, month_number = month.split("-")
    return {
        "month": month, "year": int(year), "month_number": int(month_number),
        "quarter": (int(month_number) - 1) // 3 + 1,
    }


def build_dimensions(
    genes: pl.DataFrame,
    variant_disease: pl.DataFrame,
    inheritance: pl.DataFrame,
    concepts: pl.DataFrame,
    hpo_term: pl.DataFrame,
    gene_phenotype: pl.DataFrame,
    fact_variant: pl.DataFrame,
    fact_reclassification: pl.DataFrame,
    month: str,
) -> dict[str, pl.DataFrame]:
    """Construit les dimensions du modèle en étoile."""
    inheritance_by_cui = (
        inheritance.group_by("cui", "panel")
        # `drop_nulls()` : un mode nul laisserait une chaîne vide dans la liste.
        .agg(
            pl.col("mode_inheritance").drop_nulls().sort().str.join("; ")
            .alias("modes_inheritance")
        )
    )
    # Une ligne par CUI (libellé : le premier par ordre alphabétique, stable d'un run à l'autre).
    dim_disease = (
        variant_disease.filter(pl.col("medgen_cui").is_not_null())
        .select("medgen_cui", "disease_name", "omim_id", "orpha_id", "mondo_id", "panel")
        .sort("disease_name", maintain_order=True)
        .unique(subset=["medgen_cui", "panel"], keep="first", maintain_order=True)
        .join(inheritance_by_cui, left_on=["medgen_cui", "panel"], right_on=["cui", "panel"],
              how="left")
        .join(concepts.select("cui", "clinical_summary", "panel"),
              left_on=["medgen_cui", "panel"], right_on=["cui", "panel"], how="left")
    )
    # Mois courant et tous les mois de l'historique de reclassification.
    reclassification_months = (
        fact_reclassification["changed_on"].str.slice(0, 7).unique().to_list()
        if fact_reclassification.height > 0
        else []
    )
    all_months = sorted({month, *reclassification_months})
    dim_month = pl.DataFrame([_month_row(m) for m in all_months])
    return {
        "dim_gene": genes.select("gene_symbol", "name", "description", "maplocation",
                                 "summary", "panel"),
        "dim_disease": dim_disease,
        "dim_phenotype": hpo_term.select("hpo_id", "hpo_name", "definition", "synonyms",
                                         "panel").unique(subset=["hpo_id", "panel"]),
        "bridge_gene_phenotype": gene_phenotype.select("gene_symbol", "hpo_id", "frequency",
                                                       "disease_id", "panel"),
        # Une ligne par (signification, panel), même si le libellé porte deux `clinsig_simple`.
        "dim_clinical_significance": (
            fact_variant.select("clinical_significance", "clinsig_simple", "panel")
            .sort("clinsig_simple", maintain_order=True)
            .unique(subset=["clinical_significance", "panel"], keep="first",
                    maintain_order=True)
        ),
        "dim_review_status": fact_variant.select("review_status", "panel").unique().with_columns(
            pl.col("review_status").replace_strict(_REVIEW_STATUS_STARS, default=None)
            .alias("stars")
        ),
        "dim_month": dim_month,
    }


def build_aggregates(
    fact_variant: pl.DataFrame, fact_reclassification: pl.DataFrame
) -> dict[str, pl.DataFrame]:
    """Pré-calcule les trois agrégats servis par l'application."""
    return {
        "agg_variants_by_gene_significance": (
            fact_variant.group_by("gene_symbol", "clinical_significance", "panel", "month")
            .agg(pl.len().alias("variant_count"))
        ),
        "agg_review_status": (
            fact_variant.group_by("gene_symbol", "review_status", "panel", "month")
            .agg(pl.len().alias("variant_count"))
        ),
        "agg_reclassifications_by_month": (
            # Groupé par mois (`YYYY-MM`) pour joindre `dim_month`.
            fact_reclassification.with_columns(
                pl.col("changed_on").str.slice(0, 7).alias("month")
            )
            .group_by("gene_symbol", "month", "panel")
            .agg(pl.len().alias("reclassification_count"))
        ),
    }


def _write_gold_snapshot(df: pl.DataFrame, table: str, panel: str, lake_uri: str | None) -> None:
    """Remplace les seules lignes du panel courant dans une table Gold."""
    uri = gold_table_uri(table, lake_uri)
    df.write_delta(
        uri, mode="overwrite", storage_options=storage_options(uri),
        delta_write_options={"partition_by": ["panel"], "predicate": f"panel = '{panel}'"},
    )


def silver_to_gold_analytique(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/analytique` depuis le Silver, sans aucun nettoyage (rôle du Silver)."""
    month = logical_date[:7]
    variants = read_silver("clinvar_variant", panel, lake_uri)
    variant_gene = read_silver("clinvar_variant_gene", panel, lake_uri)
    variant_disease = read_silver("clinvar_variant_disease", panel, lake_uri)

    fact_variant = build_fact_variant(variants, variant_gene, month)
    fact_variant_disease = build_fact_variant_disease(variant_disease, variant_gene, month)
    fact_reclassification = build_fact_reclassification(variants, variant_gene)

    dimensions = build_dimensions(
        read_silver("ncbi_gene", panel, lake_uri),
        variant_disease,
        read_silver("medgen_inheritance", panel, lake_uri),
        read_silver("medgen_concept", panel, lake_uri),
        read_silver("hpo_term", panel, lake_uri),
        read_silver("hpo_gene_phenotype", panel, lake_uri),
        fact_variant,
        fact_reclassification,
        month,
    )
    aggregates = build_aggregates(fact_variant, fact_reclassification)

    tables = {
        "fact_variant": fact_variant,
        "fact_variant_disease": fact_variant_disease,
        "fact_reclassification": fact_reclassification,
        **dimensions,
        **aggregates,
    }
    for table, df in tables.items():
        frame = df if "panel" in df.columns else df.with_columns(pl.lit(panel).alias("panel"))
        _write_gold_snapshot(frame, table, panel, lake_uri)
