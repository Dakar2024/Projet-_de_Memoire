"""Contrôle qualité de la couche Gold, dernier filet avant le RAG et l'application."""
from __future__ import annotations

import polars as pl

from ingestion.config import PANEL_GENES
from ingestion.storage import storage_options
from transformations.silver_io import read_silver
from transformations.silver_to_gold_analytique import gold_table_uri
from transformations.silver_to_gold_rag import documents_uri

# ~512 tokens à ~4 caractères par token, avec marge.
MAX_DOCUMENT_CHARS = 2000


class GoldQualityError(RuntimeError):
    """Un ou plusieurs contrôles qualité Gold ont échoué."""


def _read_gold(uri: str, panel: str) -> pl.DataFrame:
    """Lit une table Gold filtrée sur le panel."""
    return pl.read_delta(uri, storage_options=storage_options(uri)).filter(
        pl.col("panel") == panel
    )


def quality_check_gold(logical_date: str, panel: str, lake_uri: str | None = None) -> None:
    """Vérifie les deux cibles Gold du panel, en levant toutes les erreurs à la fois."""
    errors: list[str] = []

    current_variants = read_silver("clinvar_variant", panel, lake_uri).filter(pl.col("is_current"))
    expected_alleleids = set(current_variants["alleleid"].to_list())

    fact_variant = _read_gold(gold_table_uri("fact_variant", lake_uri), panel)
    actual_alleleids = set(fact_variant["alleleid"].to_list())
    if actual_alleleids != expected_alleleids:
        missing = len(expected_alleleids - actual_alleleids)
        extra = len(actual_alleleids - expected_alleleids)
        errors.append(
            f"fact_variant : {missing} variant(s) courant(s) absent(s), {extra} en trop"
        )

    documents = _read_gold(documents_uri(lake_uri), panel)
    variant_docs = documents.filter(pl.col("doc_type") == "variant")
    expected_doc_ids = {f"clinvar:{allele}" for allele in expected_alleleids}
    if set(variant_docs["doc_id"].to_list()) != expected_doc_ids:
        errors.append(
            f"documents : {len(expected_doc_ids)} document(s) variant attendu(s), "
            f"{variant_docs.height} présent(s)"
        )
    gene_docs = documents.filter(pl.col("doc_type") == "gene")
    if set(gene_docs["doc_id"].to_list()) != {f"gene:{g}" for g in PANEL_GENES[panel]}:
        errors.append("documents : un document de gène manque ou est en trop")

    if documents["doc_id"].n_unique() != documents.height:
        errors.append("documents : doc_id en double")
    if documents["chunk_id"].null_count() > 0:
        errors.append("documents : chunk_id nul")

    too_long = documents.filter(pl.col("text").str.len_chars() > MAX_DOCUMENT_CHARS)
    if too_long.height > 0:
        errors.append(
            f"documents : {too_long.height} document(s) au-delà de "
            f"{MAX_DOCUMENT_CHARS} caractères"
        )

    # Dimensions comparées au Silver, pour détecter une corruption simultanée fait + dimension.
    variant_gene = read_silver("clinvar_variant_gene", panel, lake_uri)
    known_genes = set(_read_gold(gold_table_uri("dim_gene", lake_uri), panel)["gene_symbol"].to_list())
    unknown_genes = set(variant_gene["gene_symbol"].drop_nulls().to_list()) - known_genes
    if unknown_genes:
        errors.append(f"dim_gene : gènes absents de la dimension : {sorted(unknown_genes)}")

    variant_disease = read_silver("clinvar_variant_disease", panel, lake_uri)
    known_cuis = set(_read_gold(gold_table_uri("dim_disease", lake_uri), panel)["medgen_cui"].to_list())
    unknown_cuis = set(variant_disease["medgen_cui"].drop_nulls().to_list()) - known_cuis
    if unknown_cuis:
        errors.append(f"dim_disease : CUI absents de la dimension : {sorted(unknown_cuis)}")

    if errors:
        raise GoldQualityError("; ".join(errors))
