"""Chargement des documents du RAG depuis `gold/rag/documents`, en lecture seule."""
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
    """Charge les documents Gold du panel, triés ; lève si un `doc_id` est en double."""
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
        # Déjà interdit par quality_check_gold : signale un Gold modifié hors pipeline.
        raise RagPermanentError(f"doc_id en double dans le Gold ({panel}) : {duplicated[:10]}")
    return documents
