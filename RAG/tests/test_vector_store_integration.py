"""Tests contre un vrai `rag-postgres`, exclus de la passe rapide (`-m integration`).
Procédure de lancement : RAG/README.md, « Tests d'intégration »."""

import os

import numpy as np
import psycopg
import pytest

from RAG.src.vectordb.vector_store import PgVectorStore

pytestmark = pytest.mark.integration

INDEXER = os.environ.get("RAG_TEST_PG_CONNINFO")
READER = os.environ.get("RAG_TEST_PG_READER_CONNINFO")
PANEL = "test_integration"
MODEL = "modele-de-test"


def _row(doc_id: str, chunk: str) -> dict:
    return {
        "doc_id": doc_id, "chunk_id": chunk, "doc_type": "variant", "text": f"texte {doc_id}",
        "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic", "review_status": "reviewed",
        "rs_dbsnp": None, "hgvs_c": "c.1A>G", "hgvs_p": None, "clinvar_variation_id": "1",
        "clinvar_url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/1/",
        "source_version": "2026-09", "collected_at": "2026-09-01",
    }


def _vectors(n: int) -> np.ndarray:
    v = np.random.default_rng(0).normal(size=(n, 768)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture
def store():
    if not INDEXER:
        pytest.skip("RAG_TEST_PG_CONNINFO absent")
    with PgVectorStore(INDEXER) as s:
        s.delete(PANEL, list(s.indexed_state(PANEL)))
        yield s
        s.delete(PANEL, list(s.indexed_state(PANEL)))


def test_upsert_then_read_state(store):
    store.upsert(PANEL, [_row("a", "h1"), _row("b", "h2")], _vectors(2), MODEL)

    assert store.indexed_state(PANEL) == {"a": ("h1", MODEL), "b": ("h2", MODEL)}


def test_upsert_updates_in_place(store):
    store.upsert(PANEL, [_row("a", "h1")], _vectors(1), MODEL)
    store.upsert(PANEL, [_row("a", "h1-bis")], _vectors(1), "autre-modele")

    assert store.indexed_state(PANEL) == {"a": ("h1-bis", "autre-modele")}


def test_delete_removes_only_the_named_documents(store):
    store.upsert(PANEL, [_row("a", "h1"), _row("b", "h2")], _vectors(2), MODEL)
    store.delete(PANEL, ["a"])

    assert store.indexed_state(PANEL) == {"b": ("h2", MODEL)}


def test_a_failed_batch_leaves_no_partial_write(store):
    rows = [_row("a", "h1"), _row("b", "h2")]
    vectors = _vectors(2)
    vectors[1] = np.nan  # la première ligne est valide : elle doit être annulée avec la seconde
    with pytest.raises(psycopg.Error):
        store.upsert(PANEL, rows, vectors, MODEL)

    assert store.indexed_state(PANEL) == {}


def test_advisory_lock_is_exclusive_between_connections(store):
    with PgVectorStore(INDEXER) as other:
        assert store.try_lock(PANEL) is True
        assert other.try_lock(PANEL) is False
        store.unlock(PANEL)
        assert other.try_lock(PANEL) is True
        other.unlock(PANEL)


def test_reader_cannot_modify_the_index(store):
    if not READER:
        pytest.skip("RAG_TEST_PG_READER_CONNINFO absent")
    store.upsert(PANEL, [_row("a", "h1")], _vectors(1), MODEL)
    with psycopg.connect(READER) as conn:
        assert conn.execute("SELECT count(*) FROM rag_documents WHERE panel = %s", (PANEL,)).fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM rag_documents WHERE panel = %s", (PANEL,))


def test_indexer_cannot_change_the_schema(store):
    with psycopg.connect(INDEXER) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DROP TABLE rag_documents")
