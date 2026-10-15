import numpy as np
import pytest

from RAG.experiments.comparaison_embeddings import (
    bootstrap_mean_ci,
    check_manifests,
    chunk_hash,
    decide,
    precision_at_k,
    reciprocal_rank,
    same_model_suspected,
)


def test_reciprocal_rank_counts_only_better_scored_candidates():
    scores = np.array([0.9, 0.5, 0.7, 0.1])

    assert reciprocal_rank(scores, target=2) == pytest.approx(1 / 2)
    assert reciprocal_rank(scores, target=0) == 1.0


def test_reciprocal_rank_respects_the_candidate_filter():
    scores = np.array([0.9, 0.5, 0.7, 0.1])
    candidates = np.array([False, True, True, True])

    assert reciprocal_rank(scores, target=2, candidates=candidates) == 1.0


def test_precision_at_k_within_a_filter():
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    relevant = np.array([True, False, True, True, False])
    candidates = np.array([False, True, True, True, True])

    assert precision_at_k(scores, relevant, k=2, candidates=candidates) == pytest.approx(0.5)


def test_precision_at_k_divides_by_k_even_with_few_candidates():
    scores = np.array([0.9, 0.8])
    relevant = np.array([True, True])

    assert precision_at_k(scores, relevant, k=10) == pytest.approx(0.2)


def test_bootstrap_is_reproducible_and_brackets_the_mean():
    diffs = np.array([0.1, 0.2, 0.0, 0.3, 0.1, 0.2])

    first = bootstrap_mean_ci(diffs)
    second = bootstrap_mean_ci(diffs)

    assert first == second
    mean, low, high = first
    assert low <= mean <= high
    assert mean == pytest.approx(diffs.mean())


def test_decision_rule_was_fixed_before_the_measurement():
    """NeuML seulement si l'écart est positif ET que l'intervalle exclut zéro."""
    assert decide(mean=0.10, low=0.02) == "neuml"
    assert decide(mean=0.10, low=-0.01) == "biobert"
    assert decide(mean=-0.05, low=-0.10) == "biobert"


def _manifest(label, fingerprint, **over):
    base = {
        "label": label, "model_id": "m", "fingerprint": fingerprint,
        "doc_ids": ["a", "b"], "chunk_hash": "c1", "questions_hash": "q1",
        "n_questions": 2, "docs_shape": [2, 4], "questions_shape": [2, 4],
    }
    return {**base, **over}


def _check(a=None, b=None, doc_ids=("a", "b"), chunks="c1", questions="q1"):
    a = a or _manifest("biobert", "f1")
    b = b or _manifest("neuml", "f2")
    check_manifests(a, b, list(doc_ids), chunks, questions)


def test_check_manifests_accepts_a_consistent_pair():
    _check()


def test_check_manifests_refuses_mismatched_doc_ids():
    with pytest.raises(SystemExit, match="documents"):
        _check(b=_manifest("neuml", "f2", doc_ids=["a", "x"]))


def test_check_manifests_refuses_changed_current_doc_ids():
    with pytest.raises(SystemExit, match="documents"):
        _check(doc_ids=("a", "b", "c"))


def test_check_manifests_refuses_mismatched_questions_hash():
    with pytest.raises(SystemExit, match="questions"):
        _check(b=_manifest("neuml", "f2", questions_hash="q2"))


def test_check_manifests_refuses_reworded_questions():
    with pytest.raises(SystemExit, match="questions"):
        _check(questions="q2")


def test_check_manifests_refuses_mismatched_chunk_hash():
    with pytest.raises(SystemExit, match="texte"):
        _check(b=_manifest("neuml", "f2", chunk_hash="c2"))


def test_check_manifests_refuses_changed_gold_text():
    with pytest.raises(SystemExit, match="texte"):
        _check(chunks="c2")


def test_check_manifests_refuses_equal_fingerprints():
    with pytest.raises(SystemExit, match="empreinte"):
        _check(b=_manifest("neuml", "f1"))


def test_check_manifests_refuses_a_wrong_label_set():
    with pytest.raises(SystemExit, match="biobert"):
        _check(b=_manifest("biobert", "f2"))


def test_check_manifests_refuses_missing_manifest():
    with pytest.raises(SystemExit, match="manquant"):
        check_manifests(None, _manifest("neuml", "f2"), ["a", "b"], "c1", "q1")


def test_chunk_hash_depends_on_content_and_order():
    assert chunk_hash(["x", "y"]) == chunk_hash(["x", "y"])
    assert chunk_hash(["x", "y"]) != chunk_hash(["y", "x"])


def test_same_model_suspected_for_near_identical_vectors():
    rng = np.random.default_rng(0)
    docs = rng.normal(size=(50, 16))
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    assert same_model_suspected(docs, docs + 1e-4)


def test_same_model_not_suspected_for_distinct_unit_vectors():
    rng = np.random.default_rng(1)
    a = rng.normal(size=(50, 16))
    b = rng.normal(size=(50, 16))
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    assert not same_model_suspected(a, b)
