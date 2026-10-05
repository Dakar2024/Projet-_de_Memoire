"""Contre le vrai rag-postgres, avec rag_reader. Exclus de la passe rapide.
Lancement : RAG/README.md, « Tests d'intégration »."""

import os

import numpy as np
import pytest

from RAG.src.retrieval.retriever import PgSearchStore
from RAG.src.vectordb.vector_store import PgVectorStore

pytestmark = pytest.mark.integration

READER = os.environ.get("RAG_TEST_PG_READER_CONNINFO")
INDEXER = os.environ.get("RAG_TEST_PG_CONNINFO")


def _vector():
    v = np.random.default_rng(1).normal(size=768).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def store():
    if not READER:
        pytest.skip("RAG_TEST_PG_READER_CONNINFO absent")
    with PgSearchStore(READER) as s:
        yield s


def test_known_significances_come_from_the_index(store):
    assert "Pathogenic" in store.known_significances()


def test_rs_with_two_variants_returns_both(store):
    found = store.exact_matches(rs=[334], hgvs_c=[], hgvs_p=[], genes=[], query_vector=_vector(), limit=10)

    assert {d.hgvs_c for d in found} >= {"c.20A>T", "c.20A>C"}
    assert all(d.stage == "exact" and d.gene_symbol == "HBB" for d in found)


def test_hgvs_is_restricted_to_the_cited_gene(store):
    found = store.exact_matches(rs=[], hgvs_c=["c.68_69del"], hgvs_p=[], genes=["BRCA1"],
                                query_vector=_vector(), limit=10)

    assert found and all(d.gene_symbol == "BRCA1" for d in found)


def test_filters_are_applied(store):
    found = store.similar(query_vector=_vector(), genes=["BRCA2"], significances=["Pathogenic"],
                          exclude_doc_ids=[], limit=10, exact=True)

    assert len(found) == 10
    assert all(d.gene_symbol == "BRCA2" and d.clinical_significance == "Pathogenic" for d in found)


def test_unfiltered_search_uses_the_hnsw_index_and_filtered_search_does_not(store):
    db = store._db
    q = _vector()
    with db.transaction():
        db.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
        plan = "\n".join(r[0] for r in db.execute(
            "EXPLAIN SELECT doc_id FROM rag_documents WHERE panel = ANY(%s::text[]) "
            "ORDER BY embedding <=> %s LIMIT 10", (["brca", "sickle"], q)).fetchall())
    assert "rag_documents_embedding_hnsw" in plan
    with db.transaction():
        db.execute("SELECT set_config('enable_indexscan', 'off', true)")
        plan = "\n".join(r[0] for r in db.execute(
            "EXPLAIN SELECT doc_id FROM rag_documents WHERE panel = ANY(%s::text[]) AND gene_symbol = 'BRCA2' "
            "ORDER BY embedding <=> %s LIMIT 10", (["brca", "sickle"], q)).fetchall())
    assert "rag_documents_embedding_hnsw" not in plan


def test_test_rows_never_surface(store):
    if not INDEXER:
        pytest.skip("RAG_TEST_PG_CONNINFO absent")
    row = {"doc_id": "clinvar:test-e2a", "chunk_id": "h", "doc_type": "variant", "text": "test",
           "gene_symbol": "HBB", "clinical_significance": "Pathogenic", "review_status": None,
           "rs_dbsnp": 334, "hgvs_c": "c.20A>T", "hgvs_p": None, "clinvar_variation_id": None,
           "clinvar_url": None, "source_version": None, "collected_at": None}
    with PgVectorStore(INDEXER) as writer:
        writer.upsert("test_integration", [row], _vector()[None, :], "modele-test")
        try:
            found = store.exact_matches(rs=[334], hgvs_c=[], hgvs_p=[], genes=[], query_vector=_vector(), limit=10)
            assert "clinvar:test-e2a" not in {d.doc_id for d in found}
        finally:
            writer.delete("test_integration", ["clinvar:test-e2a"])


def test_exact_search_stays_stable_after_many_executions(store):
    """Au-delà de 5 exécutions, un plan préparé ne doit pas changer le résultat exact."""
    q = _vector()
    kwargs = dict(query_vector=q, genes=["BRCA2"], significances=["Pathogenic"], exclude_doc_ids=[], limit=10)
    reference = None
    for _ in range(12):
        found = store.similar(exact=True, **kwargs)
        ids = [d.doc_id for d in found]
        assert all(d.gene_symbol == "BRCA2" and d.clinical_significance == "Pathogenic" for d in found)
        assert reference is None or ids == reference
        reference = ids
        store.similar(exact=False, **kwargs)


def test_index_has_a_single_model(store):
    assert len(store.index_models()) == 1


def test_exact_results_are_ordered_by_similarity_then_doc_id(store):
    """Égalités de distance départagées par doc_id, en correspondance exacte comme en
    recherche filtrée exacte."""
    q = _vector()
    exact = store.exact_matches(rs=[334], hgvs_c=[], hgvs_p=[], genes=[], query_vector=q, limit=10)
    filtered = store.similar(query_vector=q, genes=["BRCA2"], significances=["Pathogenic"], exclude_doc_ids=[],
                             limit=50, exact=True)

    for found in (exact, filtered):
        assert found
        assert found == sorted(found, key=lambda d: (-d.similarity, d.doc_id))


def test_doc_ids_fingerprint_is_stable_and_ignores_test_rows(store):
    first = store.doc_ids_sha256()
    assert len(first) == 64 and store.doc_ids_sha256() == first
    if not INDEXER:
        pytest.skip("RAG_TEST_PG_CONNINFO absent")
    row = {"doc_id": "clinvar:test-e2a-sha", "chunk_id": "h", "doc_type": "variant", "text": "test",
           "gene_symbol": "HBB", "clinical_significance": None, "review_status": None,
           "rs_dbsnp": None, "hgvs_c": None, "hgvs_p": None, "clinvar_variation_id": None,
           "clinvar_url": None, "source_version": None, "collected_at": None}
    with PgVectorStore(INDEXER) as writer:
        writer.upsert("test_integration", [row], _vector()[None, :], "modele-test")
        try:
            assert store.doc_ids_sha256() == first
        finally:
            writer.delete("test_integration", ["clinvar:test-e2a-sha"])
