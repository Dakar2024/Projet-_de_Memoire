import pytest

from RAG.src.evaluation.agreement import cluster_bootstrap_ci, cohen_kappa, weighted_kappa

YES_NO = (True, False)


def _pairs(counts):
    a, b = [], []
    for (x, y), n in counts.items():
        a += [x] * n
        b += [y] * n
    return a, b


def test_textbook_example():
    # 50 éléments : 20 oui/oui, 5 oui/non, 10 non/oui, 15 non/non -> po = 0,7, pe = 0,5, kappa = 0,4.
    a, b = _pairs({(True, True): 20, (True, False): 5, (False, True): 10, (False, False): 15})
    assert cohen_kappa(a, b, YES_NO) == pytest.approx(0.4)


def test_perfect_agreement():
    a = [True, False, True, False]
    assert cohen_kappa(a, a, YES_NO) == pytest.approx(1.0)


def test_single_category_everywhere_is_undefined():
    assert cohen_kappa([True] * 5, [True] * 5, YES_NO) is None


def test_empty_is_undefined():
    assert cohen_kappa([], [], YES_NO) is None


def test_systematic_disagreement_is_negative():
    assert cohen_kappa([True, False] * 5, [False, True] * 5, YES_NO) == pytest.approx(-1.0)


def test_weighted_kappa_hand_computed():
    # Paires (0,0) (1,1) (2,2) (0,1) (2,1) (1,2) ; poids |i-j|/2.
    # Désaccord observé pondéré : 3 × 0,5 = 1,5 ; attendu (marges 2/2/2 et 1/3/2) : 2,5.
    # kappa_w = 1 - 1,5 / 2,5 = 0,4 ; non pondéré : po = 0,5, pe = 1/3 -> 0,25.
    a = [0, 1, 2, 0, 2, 1]
    b = [0, 1, 2, 1, 1, 2]
    assert weighted_kappa(a, b, (0, 1, 2)) == pytest.approx(0.4)
    assert cohen_kappa(a, b, (0, 1, 2)) == pytest.approx(0.25)


def test_weighted_equals_unweighted_with_two_categories():
    a, b = _pairs({(0, 0): 7, (0, 1): 2, (1, 0): 3, (1, 1): 8})
    assert weighted_kappa(a, b, (0, 1)) == pytest.approx(cohen_kappa(a, b, (0, 1)))


def test_far_disagreement_weighs_more():
    near = weighted_kappa([0, 1, 2, 0], [0, 1, 2, 1], (0, 1, 2))
    far = weighted_kappa([0, 1, 2, 0], [0, 1, 2, 2], (0, 1, 2))
    assert far < near


def test_lengths_must_match():
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False], YES_NO)


def test_unknown_category_is_refused():
    with pytest.raises(ValueError):
        weighted_kappa([0, 3], [0, 1], (0, 1, 2))


def test_cluster_bootstrap_is_deterministic_and_ordered():
    clusters = [[(True, True), (False, False)], [(True, False)], [(False, False), (True, True)],
                [(False, True), (True, True)], [(True, True)], [(False, False)]]
    stat = lambda a, b: cohen_kappa(a, b, YES_NO)
    first = cluster_bootstrap_ci(clusters, stat, seed=1, n_resamples=500)
    assert first == cluster_bootstrap_ci(clusters, stat, seed=1, n_resamples=500)
    low, high = first
    assert -1.0 <= low <= high <= 1.0


def test_cluster_bootstrap_keeps_clusters_whole():
    seen = []

    def stat(a, b):
        seen.append(len(a))
        return 0.0

    cluster_bootstrap_ci([[(1, 1)] * 3, [(1, 1)] * 5], stat, seed=0, n_resamples=50)
    assert set(seen) <= {6, 8, 10}


def test_cluster_bootstrap_without_valid_draw():
    assert cluster_bootstrap_ci([[(True, True)]], lambda a, b: None, seed=0, n_resamples=10) == (None, None)
    assert cluster_bootstrap_ci([], lambda a, b: 0.0, seed=0) == (None, None)
