"""Règle de choix du modèle de génération, fixée avant la mesure (spec E3a §8) : élimination, fidélité, pertinence, coût, latence."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from RAG.src.evaluation.settings import Thresholds

_Z95 = 1.96
_COST_EPS = 1e-9


@dataclass(frozen=True)
class CandidateResult:
    """Scores d'un candidat, par question, et ses taux, coût et latence."""
    name: str
    faithfulness: dict[str, float]          # question -> fidélité (réponses jugées, ≥ 1 affirmation)
    relevance: dict[str, float]             # question -> note / 2 (réponses jugées)
    rejection_rate: float
    wrong_abstention_rate: float
    mean_cost: float
    median_latency_ms: float
    repeat_faithfulness: dict[str, list[float]] = field(default_factory=dict)  # question -> passages
    repeat_relevance: dict[str, list[float]] = field(default_factory=dict)

    @property
    def mean_faithfulness(self) -> float | None:
        """Fidélité moyenne, ou None sans réponse jugée."""
        return float(np.mean(list(self.faithfulness.values()))) if self.faithfulness else None

    @property
    def mean_relevance(self) -> float | None:
        """Pertinence moyenne, ou None sans réponse jugée."""
        return float(np.mean(list(self.relevance.values()))) if self.relevance else None


@dataclass(frozen=True)
class Decision:
    """Candidat retenu, motifs d'élimination et trace de chaque comparaison."""
    chosen: str | None
    eliminated: dict[str, list[str]]
    steps: list[dict]


def bootstrap_mean_ci(diffs, n_resamples: int = 10_000, seed: int = 20261001,
                      alpha: float = 0.05) -> tuple[float, float, float]:
    """Calcule moyenne et IC bootstrap des écarts appariés (même algorithme que comparaison_embeddings, vérifié par test)."""
    values = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n_resamples, len(values)))].mean(axis=1)
    return float(values.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def run_variance(repeats: dict[str, list[float]]) -> float:
    """Calcule la variance moyenne des scores d'un passage à l'autre, sur les questions reprises."""
    variances = [float(np.var(v, ddof=1)) for v in repeats.values() if len(v) >= 2]
    return float(np.mean(variances)) if variances else 0.0


def noise_margin(va: float, vb: float, n: int) -> float:
    """Borne à 95 % du bruit d'un passage à l'autre sur l'écart de deux moyennes de n questions."""
    if n <= 0:
        raise ValueError("n doit être positif")
    return _Z95 * math.sqrt((va + vb) / n)


def eliminate(result: CandidateResult, t: Thresholds) -> list[str]:
    """Renvoie les motifs d'élimination d'un candidat (vide s'il reste en lice)."""
    reasons = []
    mean = result.mean_faithfulness
    if mean is None:
        reasons.append("aucune réponse jugée")
    elif mean < t.faithfulness_min:
        reasons.append(f"fidélité {mean:.3f} < {t.faithfulness_min}")
    if result.rejection_rate > t.rejection_max:
        reasons.append(f"rejet {result.rejection_rate:.3f} > {t.rejection_max}")
    if result.wrong_abstention_rate > t.wrong_abstention_max:
        reasons.append(f"abstention à tort {result.wrong_abstention_rate:.3f} > {t.wrong_abstention_max}")
    return reasons


def _ties(candidates: list[CandidateResult], metric: str, seed: int) -> tuple[list[CandidateResult], list[dict]]:
    """Candidats à égalité avec le meilleur pour `metric` ("faithfulness" ou "relevance")."""
    scores: Callable[[CandidateResult], dict[str, float]] = lambda c: getattr(c, metric)  # noqa: E731
    repeats: Callable[[CandidateResult], dict[str, list[float]]] = lambda c: getattr(c, f"repeat_{metric}")  # noqa: E731
    means = {c.name: float(np.mean(list(scores(c).values()))) if scores(c) else -1.0 for c in candidates}
    best = max(candidates, key=lambda c: (means[c.name], c.name))
    tied, steps = [best], []
    for other in candidates:
        if other is best:
            continue
        common = sorted(set(scores(best)) & set(scores(other)))
        step = {"metrique": metric, "meilleur": best.name, "candidat": other.name, "n": len(common)}
        if len(common) < 2:
            step.update(egalite=True, motif="moins de deux questions jugées en commun")
            tied.append(other)
            steps.append(step)
            continue
        diffs = np.array([scores(best)[q] - scores(other)[q] for q in common])
        mean, low, high = bootstrap_mean_ci(diffs, seed=seed)
        eps = noise_margin(run_variance(repeats(best)), run_variance(repeats(other)), len(common))
        worse = low > 0 and abs(mean) >= eps
        step.update(ecart=mean, ic_bas=low, ic_haut=high, epsilon=eps, egalite=not worse,
                    motif=("écart établi" if worse else "IC non strictement positif" if low <= 0
                           else "écart inférieur au bruit des passages"))
        if not worse:
            tied.append(other)
        steps.append(step)
    return tied, steps


def choose(results: list[CandidateResult], thresholds: Thresholds, *, use_relevance: bool, seed: int) -> Decision:
    """Applique la règle de choix et renvoie la décision tracée."""
    eliminated = {r.name: reasons for r in results if (reasons := eliminate(r, thresholds))}
    remaining = [r for r in results if r.name not in eliminated]
    steps: list[dict] = []
    if not remaining:
        return Decision(chosen=None, eliminated=eliminated, steps=[{"etape": "tous éliminés"}])
    tied, s = _ties(remaining, "faithfulness", seed)
    steps += s
    if len(tied) > 1 and use_relevance:
        tied, s = _ties(tied, "relevance", seed)
        steps += s
    elif len(tied) > 1:
        steps.append({"etape": "pertinence sautée (kappa insuffisant)"})
    if len(tied) > 1:
        cheapest = min(r.mean_cost for r in tied)
        tied = [r for r in tied if r.mean_cost - cheapest <= _COST_EPS]
        steps.append({"etape": "coût", "restants": [r.name for r in tied]})
    if len(tied) > 1:
        tied = [min(tied, key=lambda r: (r.median_latency_ms, r.name))]
        steps.append({"etape": "latence", "restants": [tied[0].name]})
    return Decision(chosen=tied[0].name, eliminated=eliminated, steps=steps)
