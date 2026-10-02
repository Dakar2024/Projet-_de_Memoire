"""Indexation d'un panel : `gold/rag/documents` → `rag_documents` (pgvector).

Ordre voulu : tout ce qui peut refuser (verrou, canari, garde-fou, longueur) passe
avant la première écriture. Ensuite seulement viennent les suppressions, puis les
vecteurs, lot par lot. Chaque lot est validé à part : une interruption ne perd que le
lot en cours, et la relance recalcule l'écart pour ne faire que le reste.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import polars as pl

from ingestion.config import PANEL_GENES
from RAG.src.chunking.chunker import check_token_lengths
from RAG.src.embeddings.canary import Canary, load_canary, verify_canary
from RAG.src.embeddings.embedder import EmbeddingClient
from RAG.src.ingestion.loader import load_gold_documents
from RAG.src.utils.config import RagConfig, load_config, load_service_settings
from RAG.src.utils.diff import check_deletion_guard, plan_sync
from RAG.src.utils.errors import IndexConsistencyError, IndexLockedError, RagConfigurationError
from RAG.src.vectordb.vector_store import PgVectorStore, VectorStore

log = logging.getLogger(__name__)

_PROGRESS_EVERY = 50


@dataclass(frozen=True)
class IndexReport:
    panel: str
    deleted: int
    embedded: int
    unchanged: int
    canary_cosine: float


def index_documents(
    panel: str,
    *,
    documents: pl.DataFrame,
    store: VectorStore,
    client,
    config: RagConfig,
    canary: Canary,
    force_deletions: bool = False,
) -> IndexReport:
    fingerprint = config.embedding.fingerprint
    if not store.try_lock(panel):
        raise IndexLockedError(f"une indexation du panel {panel} est déjà en cours")
    try:
        cosine = verify_canary(client, canary, fingerprint, config.embedding.canary_min_cosine)
        gold = dict(zip(documents["doc_id"].to_list(), documents["chunk_id"].to_list(), strict=True))
        indexed = store.indexed_state(panel)
        plan = plan_sync(gold, indexed, fingerprint)
        check_deletion_guard(plan, len(gold), len(indexed), config.index.max_delete_ratio, force_deletions)

        todo = documents.filter(pl.col("doc_id").is_in(plan.to_embed))
        if todo.height:
            check_token_lengths(
                todo["doc_id"].to_list(), todo["text"].to_list(), client.token_counts, client.max_input_length()
            )
        log.info("panel %s : %d à vectoriser, %d à supprimer, %d inchangés (canari %.6f)",
                 panel, len(plan.to_embed), len(plan.to_delete), plan.unchanged, cosine)

        store.delete(panel, plan.to_delete)
        batches = todo.iter_slices(config.embedding.batch_size)
        for number, batch in enumerate(batches, start=1):
            store.upsert(panel, batch.to_dicts(), client.embed(batch["text"].to_list()), fingerprint)
            if number % _PROGRESS_EVERY == 0:
                log.info("panel %s : %d documents vectorisés", panel, min(number * config.embedding.batch_size, todo.height))

        expected = {doc_id: (chunk, fingerprint) for doc_id, chunk in gold.items()}
        actual = store.indexed_state(panel)
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            stale = sorted(d for d in set(expected) & set(actual) if expected[d] != actual[d])
            raise IndexConsistencyError(
                f"index ≠ Gold pour {panel} : {len(missing)} manquants {missing[:5]}, "
                f"{len(extra)} en trop {extra[:5]}, {len(stale)} périmés {stale[:5]}"
            )
        return IndexReport(panel, len(plan.to_delete), len(plan.to_embed), plan.unchanged, cosine)
    finally:
        store.unlock(panel)


def run_index(panel: str, lake_uri: str | None = None, force_deletions: bool = False) -> IndexReport:
    """Câblage réel, appelé par la tâche Airflow `index_rag_documents`."""
    if panel not in PANEL_GENES:
        raise RagConfigurationError(f"panel inconnu : {panel!r}")
    config = load_config()
    services = load_service_settings()
    canary = load_canary(config.embedding.canary_path)
    client = EmbeddingClient(
        services.embeddings_url, services.embeddings_api_key, timeout_s=config.embedding.request_timeout_s
    )
    documents = load_gold_documents(panel, lake_uri)
    with PgVectorStore(services.pg_conninfo) as store:
        report = index_documents(
            panel, documents=documents, store=store, client=client,
            config=config, canary=canary, force_deletions=force_deletions,
        )
    log.info("indexation %s terminée : %s", panel, report)
    return report
