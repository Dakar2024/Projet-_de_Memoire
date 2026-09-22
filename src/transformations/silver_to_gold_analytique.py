from __future__ import annotations

import polars as pl

from ingestion.storage import layer_uri, storage_options
from transformations import SPEC
from transformations.silver_io import read_silver

# Rang de confiance publié par ClinVar pour chaque statut de revue (0 à 4 étoiles).
# Correspondance externe, pas un regroupement inventé ici.
_REVIEW_STATUS_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
    "no classification provided": 0,
    "no classification for the single variant": 0,
}


def gold_table_uri(table: str, lake_uri: str | None = None) -> str:
    return f"{layer_uri('gold', lake_uri=lake_uri)}/analytique/{table}"


def build_fact_variant(
    variants: pl.DataFrame, variant_gene: pl.DataFrame, month: str
) -> pl.DataFrame:
    """Un variant courant par ligne. La jointure sur `clinvar_variant_gene` donne le
    gène du panel ; un variant rattaché à deux gènes du panel produit deux lignes —
    d'où un contrôle qualité sur le nombre d'`alleleid` distincts, pas de lignes."""
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
    """Pont variant × maladie : compter les variants par maladie sans surcompter
    `fact_variant`, dont le grain est le variant."""
    return (
        variant_disease.join(
            variant_gene.select("alleleid", "gene_symbol"), on="alleleid", how="left"
        )
        .select("alleleid", "medgen_cui", "disease_name", "gene_symbol", "panel",
                pl.lit(month).alias("month"))
    )


def build_fact_reclassification(variants: pl.DataFrame) -> pl.DataFrame:
    """Une ligne par transition SCD2 : la ligne clôturée est appariée à celle qui lui
    succède (`valid_from` de la suivante == `valid_to` de la précédente)."""
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
        .select(
            "alleleid",
            pl.col("genesymbol").alias("gene_symbol"),
            pl.col("clinicalsignificance").alias("significance_from"),
            "significance_to",
            "review_status_to",
            pl.col("valid_to").alias("changed_on"),
            "panel",
        )
    )


def build_dimensions(
    genes: pl.DataFrame,
    variant_disease: pl.DataFrame,
    inheritance: pl.DataFrame,
    concepts: pl.DataFrame,
    hpo_term: pl.DataFrame,
    gene_phenotype: pl.DataFrame,
    fact_variant: pl.DataFrame,
    month: str,
) -> dict[str, pl.DataFrame]:
    inheritance_by_cui = (
        inheritance.group_by("cui", "panel")
        # `drop_nulls()` avant la jointure : un mode nul produirait sinon une chaîne
        # vide parasite au milieu de la liste (vérifié sur Polars 1.44).
        .agg(
            pl.col("mode_inheritance").drop_nulls().sort().str.join("; ")
            .alias("modes_inheritance")
        )
    )
    dim_disease = (
        variant_disease.select("medgen_cui", "disease_name", "omim_id", "orpha_id",
                               "mondo_id", "panel")
        .unique(subset=["medgen_cui", "disease_name"], keep="first")
        .join(inheritance_by_cui, left_on=["medgen_cui", "panel"], right_on=["cui", "panel"],
              how="left")
        .join(concepts.select("cui", "clinical_summary", "panel"),
              left_on=["medgen_cui", "panel"], right_on=["cui", "panel"], how="left")
    )
    year, month_number = month.split("-")
    dim_month = pl.DataFrame([{
        "month": month, "year": int(year), "month_number": int(month_number),
        "quarter": (int(month_number) - 1) // 3 + 1,
    }])
    return {
        "dim_gene": genes.select("gene_symbol", "name", "description", "maplocation",
                                 "summary", "panel"),
        "dim_disease": dim_disease,
        "dim_phenotype": hpo_term.select("hpo_id", "hpo_name", "definition", "synonyms",
                                         "panel").unique(subset=["hpo_id", "panel"]),
        "bridge_gene_phenotype": gene_phenotype.select("gene_symbol", "hpo_id", "frequency",
                                                       "disease_id", "panel"),
        "dim_clinical_significance": fact_variant.select(
            pl.col("clinical_significance"), pl.col("clinsig_simple"), "panel"
        ).unique(),
        "dim_review_status": fact_variant.select("review_status", "panel").unique().with_columns(
            pl.col("review_status").replace_strict(_REVIEW_STATUS_STARS, default=None)
            .alias("stars")
        ),
        "dim_month": dim_month,
    }


def silver_to_gold_analytique(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/analytique/` (Delta) : modèle en étoile et agrégats.

    `fact_variant` et ses dimensions (gène, maladie, phénotype, signification
    clinique, temps). Agrégats : nombre de variants par gène et par signification,
    répartition des statuts de revue, reclassifications par mois. Lu par DuckDB pour
    l'application. Lit le Silver, jamais `gold/rag/`.

    Interdit : nettoyer. Le Silver est la seule couche qui nettoie ; une donnée qui
    arrive ici incorrecte se corrige dans `bronze_to_silver`, pas dans le Gold.
    """
    raise NotImplementedError(
        f"silver_to_gold_analytique : implémenté par le sous-projet D ({SPEC}, §7)"
    )
