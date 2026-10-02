from pathlib import Path

import numpy as np
import polars as pl
import pytest

from RAG.src.embeddings.canary import CANARY_PHRASES, Canary
from RAG.src.ingestion.indexer import index_documents
from RAG.src.ingestion.loader import DOCUMENT_COLUMNS
from RAG.src.utils.config import EmbeddingSettings, IndexSettings, RagConfig
from RAG.src.utils.errors import (
    CanaryMismatchError,
    DocumentTooLongError,
    IndexConsistencyError,
    IndexLockedError,
    MassDeletionError,
)
from RAG.tests.fakes import FakeEmbeddingClient, InMemoryStore, vector_for

FP = "modele@abc+onnx:123"


def _config(batch_size: int = 2) -> RagConfig:
    return RagConfig(
        embedding=EmbeddingSettings(FP, Path("canari.json"), 0.995, batch_size, 60.0),
        index=IndexSettings(max_delete_ratio=0.05),
    )


def _canary(fingerprint: str = FP) -> Canary:
    return Canary(fingerprint, CANARY_PHRASES, np.stack([vector_for(p) for p in CANARY_PHRASES]))


def _documents(n: int, version: str = "v1") -> pl.DataFrame:
    rows = []
    for i in range(n):
        text = f"document {i} {version}"
        rows.append({column: None for column in DOCUMENT_COLUMNS} | {
            "doc_id": f"clinvar:{i:03d}", "chunk_id": f"h-{i}-{version}", "doc_type": "variant",
            "text": text, "gene_symbol": "BRCA1",
        })
    return pl.DataFrame(rows, schema={c: pl.Utf8 for c in DOCUMENT_COLUMNS} | {"rs_dbsnp": pl.Int64})


def _run(store, client, documents, **kwargs):
    return index_documents("brca", documents=documents, store=store, client=client,
                           config=kwargs.pop("config", _config()), canary=kwargs.pop("canary", _canary()),
                           **kwargs)


def test_first_run_indexes_every_document():
    store, client = InMemoryStore(), FakeEmbeddingClient()

    report = _run(store, client, _documents(5))

    assert (report.embedded, report.deleted, report.unchanged) == (5, 0, 0)
    assert len(store.indexed_state("brca")) == 5
    assert store.locked == set()


def test_replaying_the_same_gold_embeds_and_writes_nothing():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    _run(store, client, _documents(5))
    writes, embedded = store.writes, len(client.embedded)

    report = _run(store, client, _documents(5))

    assert report.embedded == 0 and report.unchanged == 5
    assert store.writes == writes
    # Seul le canari a été vectorisé au second passage.
    assert client.embedded[embedded:] == list(CANARY_PHRASES)


def test_only_changed_documents_are_reembedded():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    documents = _documents(4)
    _run(store, client, documents)
    changed = documents.with_columns(
        pl.when(pl.col("doc_id") == "clinvar:002").then(pl.lit("h-2-v2")).otherwise(pl.col("chunk_id")).alias("chunk_id")
    )

    report = _run(store, client, changed)

    assert report.embedded == 1
    assert store.indexed_state("brca")["clinvar:002"] == ("h-2-v2", FP)


def test_a_document_gone_from_gold_is_deleted():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    _run(store, client, _documents(40))

    report = _run(store, client, _documents(40).filter(pl.col("doc_id") != "clinvar:007"))

    assert report.deleted == 1
    assert "clinvar:007" not in store.indexed_state("brca")


def test_resumes_after_an_interruption_without_recomputing():
    """Une indexation coupée au milieu ne refait, à la relance, que les lots manquants."""
    store, client = InMemoryStore(fail_after_upserts=2), FakeEmbeddingClient()
    with pytest.raises(ConnectionError):
        _run(store, client, _documents(10))
    assert len(store.indexed_state("brca")) == 4
    assert store.locked == set(), "le verrou doit être rendu même après une erreur"

    store._fail_after = None
    resumed = FakeEmbeddingClient()
    report = _run(store, resumed, _documents(10))

    assert report.embedded == 6 and report.unchanged == 4
    assert len(resumed.embedded) == len(CANARY_PHRASES) + 6


def test_second_indexation_of_the_same_panel_is_refused():
    store = InMemoryStore()
    store.try_lock("brca")

    with pytest.raises(IndexLockedError):
        _run(store, FakeEmbeddingClient(), _documents(3))
    assert store.indexed_state("brca") == {}


def test_a_wrong_model_writes_nothing():
    store, client = InMemoryStore(), FakeEmbeddingClient()

    with pytest.raises(CanaryMismatchError):
        _run(store, client, _documents(3), canary=_canary("autre@modele"))
    assert store.writes == 0


def test_an_overlong_document_writes_nothing_not_even_deletions():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    _run(store, client, _documents(40))
    documents = _documents(40).filter(pl.col("doc_id") != "clinvar:000").with_columns(
        pl.when(pl.col("doc_id") == "clinvar:001").then(pl.lit("mot " * 600)).otherwise(pl.col("text")).alias("text"),
        pl.when(pl.col("doc_id") == "clinvar:001").then(pl.lit("h-long")).otherwise(pl.col("chunk_id")).alias("chunk_id"),
    )
    writes = store.writes

    with pytest.raises(DocumentTooLongError, match="clinvar:001"):
        _run(store, client, documents)
    assert store.writes == writes


def test_refuses_to_index_an_empty_gold():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    _run(store, client, _documents(3))

    with pytest.raises(MassDeletionError, match="vide"):
        _run(store, client, _documents(0))
    assert len(store.indexed_state("brca")) == 3


def test_force_deletions_allows_a_real_mass_removal():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    _run(store, client, _documents(10))

    with pytest.raises(MassDeletionError):
        _run(store, client, _documents(5))
    report = _run(store, client, _documents(5), force_deletions=True)

    assert report.deleted == 5


def test_a_store_that_loses_writes_is_detected():
    class LossyStore(InMemoryStore):
        def upsert(self, panel, rows, vectors, embedding_model):
            super().upsert(panel, rows[:-1], vectors[:-1], embedding_model)

    with pytest.raises(IndexConsistencyError):
        _run(LossyStore(), FakeEmbeddingClient(), _documents(4))


def test_other_panels_are_untouched():
    store, client = InMemoryStore(), FakeEmbeddingClient()
    store.upsert("sickle", [{"doc_id": "gene:HBB", "chunk_id": "x"}], np.zeros((1, 768), np.float32), FP)

    _run(store, client, _documents(3))

    assert store.indexed_state("sickle") == {"gene:HBB": ("x", FP)}
