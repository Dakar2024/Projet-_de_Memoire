from __future__ import annotations

import polars as pl

from ingestion.storage import layer_uri, storage_options
from transformations.silver_io import read_silver

# Rang de confiance publié par ClinVar pour chaque statut de revue (0 à 4 étoiles).
# Correspondance externe, pas un regroupement inventé ici. Vocabulaire ClinVar complet ;
# "-" est délibérément absent (donc `replace_strict(..., default=None)` le laisse nul) :
# "-" signifie que ClinVar n'a donné aucun statut de revue, et 0 étoile affirmerait à
# tort une revue à zéro étoile là où la source ne dit rien.
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
    return f"{layer_uri('gold', lake_uri=lake_uri)}/analytique/{table}"


def build_fact_variant(
    variants: pl.DataFrame, variant_gene: pl.DataFrame, month: str
) -> pl.DataFrame:
    """Une ligne par (variant courant, gène du panel) : la jointure sur
    `clinvar_variant_gene` donne le gène du panel, et un variant rattaché à deux gènes
    du panel produit deux lignes avec le même `alleleid` et des `gene_symbol`
    différents — d'où un contrôle qualité sur le nombre d'`alleleid` distincts, pas de
    lignes. En pratique cela équivaut à une ligne par variant : aucun variant des deux
    panels ne se rattache aujourd'hui à deux gènes du panel."""
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


def build_fact_reclassification(
    variants: pl.DataFrame, variant_gene: pl.DataFrame
) -> pl.DataFrame:
    """Une ligne par transition SCD2 : la ligne clôturée est appariée à celle qui lui
    succède (`valid_from` de la suivante == `valid_to` de la précédente).

    `gene_symbol` vient de `clinvar_variant_gene`, pas de `genesymbol` sur
    `clinvar_variant` : cette dernière colonne garde la chaîne brute ClinVar,
    potentiellement multi-gène (`"ATM;C11orf65"`) — exactement ce que
    `clinvar_variant_gene` explose sur `;` — et ne joindrait à rien dans
    `dim_gene`. Même source que `build_fact_variant`."""
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
    inheritance_by_cui = (
        inheritance.group_by("cui", "panel")
        # `drop_nulls()` avant la jointure : un mode nul produirait sinon une chaîne
        # vide parasite au milieu de la liste (vérifié sur Polars 1.44).
        .agg(
            pl.col("mode_inheritance").drop_nulls().sort().str.join("; ")
            .alias("modes_inheritance")
        )
    )
    # Une ligne par `medgen_cui` (§5.3 de la spec), pas par (medgen_cui, disease_name) :
    # un CUI porté par deux libellés ClinVar ne doit pas doubler la dimension, sinon
    # une jointure `fact_variant_disease -> dim_disease` compte ce CUI deux fois. Les
    # lignes sans CUI (nul) n'ont aucune clé à porter dans la dimension et sont
    # écartées ici ; `fact_variant_disease`, lui, les garde — c'est le pont qui
    # préserve toutes les lignes du Silver, pas la dimension. Tri déterministe avant
    # le `unique(keep="first")` : quel libellé représente le CUI est un choix
    # arbitraire assumé (le premier par ordre alphabétique), mais il doit être stable
    # d'un run à l'autre.
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
    # `dim_month` couvre le mois courant et tout mois déjà présent dans l'historique
    # de reclassification : `fact_reclassification` conserve tout l'historique SCD2
    # du Silver (pas seulement les transitions de ce run), donc un `dim_month` limité
    # au mois courant laisserait les mois passés sans ligne de dimension alors que
    # les faits qui les référencent existent toujours.
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
        # Une ligne par (clinical_significance, panel) : un libellé porté par les deux
        # valeurs de `clinsig_simple` dans les données (ex. "Conflicting
        # classifications of pathogenicity") ne doit pas non plus doubler cette
        # dimension — même défaut, même correctif que `dim_disease` ci-dessus.
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
    """Trois agrégats pré-calculés : le backend de l'application sert une ligne déjà
    calculée plutôt que de parcourir ~97 000 variants à chaque requête."""
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
            # `changed_on` est une date exacte (`YYYY-MM-DD`) ; `dim_month.month` est
            # `YYYY-MM`. Grouper sur `changed_on` ne joignait jamais `dim_month` et
            # éclatait un même mois en autant de lignes que de jours distincts.
            fact_reclassification.with_columns(
                pl.col("changed_on").str.slice(0, 7).alias("month")
            )
            .group_by("gene_symbol", "month", "panel")
            .agg(pl.len().alias("reclassification_count"))
        ),
    }


def _write_gold_snapshot(df: pl.DataFrame, table: str, panel: str, lake_uri: str | None) -> None:
    """Remplace les seules lignes du panel : sans `predicate`, chaque run effacerait
    l'autre panel — même protection que `_write_silver_snapshot`."""
    uri = gold_table_uri(table, lake_uri)
    df.write_delta(
        uri, mode="overwrite", storage_options=storage_options(uri),
        delta_write_options={"partition_by": ["panel"], "predicate": f"panel = '{panel}'"},
    )


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
