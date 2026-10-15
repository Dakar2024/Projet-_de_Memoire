import math

import numpy as np
import pytest

from RAG.experiments.comparaison_embeddings import bootstrap_mean_ci as e1_bootstrap
from RAG.src.evaluation.decision import (
    CandidateResult, bootstrap_mean_ci, choose, eliminate, noise_margin, run_variance,
)
from RAG.src.evaluation.settings import Thresholds

T = Thresholds(faithfulness_min=0.90, rejection_max=0.25, wrong_abstention_max=0.10, kappa_min=0.6)
QIDS = [f"q{i:02d}" for i in range(40)]


def cand(name, faith, rel=1.0, *, rejection=0.1, abstention=0.0, cost=0.01, latency=1000.0,
         repeat=None, repeat_rel=None):
    faithfulness = faith if isinstance(faith, dict) else {q: faith for q in QIDS}
    relevance = rel if isinstance(rel, dict) else {q: rel for q in QIDS}
    return CandidateResult(name=name, faithfulness=faithfulness, relevance=relevance, rejection_rate=rejection,
                           wrong_abstention_rate=abstention, mean_cost=cost, median_latency_ms=latency,
                           repeat_faithfulness=repeat or {}, repeat_relevance=repeat_rel or {})


def noisy(base, spread, seed):
    rng = np.random.default_rng(seed)
    return {q: float(np.clip(base + rng.uniform(-spread, spread), 0, 1)) for q in QIDS}


def test_same_bootstrap_as_e1():
    diffs = np.random.default_rng(3).normal(size=30)
    assert bootstrap_mean_ci(diffs, seed=20261001) == e1_bootstrap(diffs, seed=20261001)


def test_noise_margin():
    assert noise_margin(0.01, 0.01, 50) == pytest.approx(1.96 * math.sqrt(0.02 / 50))
    with pytest.raises(ValueError):
        noise_margin(0.1, 0.1, 0)


def test_run_variance_ignores_single_runs():
    assert run_variance({"a": [1.0, 0.0, 1.0], "b": [0.5]}) == pytest.approx(np.var([1, 0, 1], ddof=1))
    assert run_variance({}) == 0.0


@pytest.mark.parametrize("kwargs,word", [
    ({"faith": 0.85}, "fidélité"),
    ({"faith": 0.95, "rejection": 0.30}, "rejet"),
    ({"faith": 0.95, "abstention": 0.11}, "abstention"),
    ({"faith": {}}, "aucune réponse"),
])
def test_each_threshold_eliminates(kwargs, word):
    reasons = eliminate(cand("x", **kwargs), T)
    assert len(reasons) == 1 and word in reasons[0]


def test_thresholds_are_inclusive():
    assert eliminate(cand("x", 0.90, rejection=0.25, abstention=0.10), T) == []


def test_all_eliminated_chooses_nothing():
    d = choose([cand("a", 0.5), cand("b", 0.8)], T, use_relevance=True, seed=1)
    assert d.chosen is None
    assert set(d.eliminated) == {"a", "b"}


def test_clear_winner_on_faithfulness():
    d = choose([cand("a", noisy(0.99, 0.01, 1), cost=1.0), cand("b", noisy(0.92, 0.01, 2), cost=0.0)],
               T, use_relevance=True, seed=1)
    assert d.chosen == "a"
    step = d.steps[0]
    assert step["egalite"] is False and step["ic_bas"] > 0


def test_tie_by_interval_goes_to_relevance():
    d = choose([cand("a", noisy(0.95, 0.05, 1), rel=0.9), cand("b", noisy(0.95, 0.05, 2), rel=0.6)],
               T, use_relevance=True, seed=1)
    assert d.chosen == "a"
    assert [s["metrique"] for s in d.steps if "metrique" in s] == ["faithfulness", "relevance"]
    assert d.steps[0]["egalite"] is True


def test_tie_by_run_noise_only():
    # Écart constant de 0,02 : IC strictement positif, mais les passages varient bien plus.
    a = {q: 0.97 for q in QIDS}
    b = {q: 0.95 for q in QIDS}
    shaky = {q: [0.7, 1.0, 0.85] for q in QIDS[:20]}
    d = choose([cand("a", a, rel=0.5, repeat=shaky), cand("b", b, rel=1.0, repeat=shaky)],
               T, use_relevance=True, seed=1)
    first = d.steps[0]
    assert first["ic_bas"] > 0 and first["egalite"] is True
    assert first["motif"] == "écart inférieur au bruit des passages"
    assert d.chosen == "b"  # départagé par la pertinence


def test_without_relevance_cost_decides():
    d = choose([cand("a", 0.95, rel=1.0, cost=0.05), cand("b", 0.95, rel=0.1, cost=0.01)],
               T, use_relevance=False, seed=1)
    assert d.chosen == "b"
    assert {"etape": "pertinence sautée (kappa insuffisant)"} in d.steps


def test_relevance_tie_then_cost():
    d = choose([cand("a", 0.95, rel=0.8, cost=0.05), cand("b", 0.95, rel=0.8, cost=0.01)],
               T, use_relevance=True, seed=1)
    assert d.chosen == "b"


def test_equal_cost_then_latency():
    d = choose([cand("a", 0.95, cost=0.01, latency=900.0), cand("b", 0.95, cost=0.01, latency=500.0)],
               T, use_relevance=True, seed=1)
    assert d.chosen == "b"
    assert d.steps[-1]["etape"] == "latence"


def test_single_common_question_is_a_declared_tie():
    d = choose([cand("a", {"q00": 1.0, "q01": 1.0}, cost=0.05), cand("b", {"q01": 0.95, "q02": 1.0}, cost=0.01)],
               T, use_relevance=False, seed=1)
    assert d.steps[0]["egalite"] is True
    assert "moins de deux" in d.steps[0]["motif"]
    assert d.chosen == "b"


def test_eliminated_candidates_never_compete():
    d = choose([cand("a", 0.99, rejection=0.5), cand("b", 0.91)], T, use_relevance=True, seed=1)
    assert d.chosen == "b"
    assert "a" in d.eliminated


def test_deterministic():
    args = ([cand("a", noisy(0.95, 0.05, 1)), cand("b", noisy(0.94, 0.05, 2))], T)
    assert choose(*args, use_relevance=True, seed=7) == choose(*args, use_relevance=True, seed=7)
