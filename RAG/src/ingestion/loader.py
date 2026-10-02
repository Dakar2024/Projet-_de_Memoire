"""Chargement des documents du RAG depuis `gold/rag/documents`.

`ingestion/` désigne ici, comme sur le schéma de référence du RAG, le chargement des
documents à indexer. La collecte des API publiques vit dans `src/ingestion/`, que ce
module réutilise pour l'accès au lac (`storage_options`) sans jamais y écrire.
"""

from __future__ import annotations

import polars as pl
from deltalake import DeltaTable

from ingestion.storage import storage_options
from RAG.src.utils.errors import RagPermanentError
from transformations.silver_to_gold_rag import documents_uri

DOCUMENT_COLUMNS = [
    "doc_id", "chunk_id", "doc_type", "text", "gene_symbol", "clinical_significance",
    "review_status", "rs_dbsnp", "hgvs_c", "hgvs_p", "clinvar_variation_id", "clinvar_url",
    "source_version", "collected_at",
]

_EMPTY_SCHEMA = {column: pl.Utf8 for column in DOCUMENT_COLUMNS} | {"rs_dbsnp": pl.Int64}


def load_gold_documents(panel: str, lake_uri: str | None = None) -> pl.DataFrame:
    uri = documents_uri(lake_uri)
    options = storage_options(uri)
    if not DeltaTable.is_deltatable(uri, storage_options=options):
        return pl.DataFrame(schema=_EMPTY_SCHEMA)
    documents = (
        pl.read_delta(uri, storage_options=options)
        .filter(pl.col("panel") == panel)
        .select(DOCUMENT_COLUMNS)
        .sort("doc_id")
    )
    duplicated = documents.filter(pl.col("doc_id").is_duplicated())["doc_id"].unique().to_list()
    if duplicated:
        # quality_check_gold l'interdit déjà : le revoir ici signale un Gold modifié
        # hors pipeline, que l'index ne doit pas recopier.
        raise RagPermanentError(f"doc_id en double dans le Gold ({panel}) : {duplicated[:10]}")
    return documents
