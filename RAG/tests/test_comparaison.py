import numpy as np
import pytest

from RAG.experiments.comparaison_embeddings import (
    bootstrap_mean_ci,
    decide,
    precision_at_k,
    reciprocal_rank,
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
