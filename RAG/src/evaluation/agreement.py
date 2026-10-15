"""Accord juge / annotation humaine (spec E3a §7.3) : kappa de Cohen, kappa pondéré, IC par bootstrap de grappes."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence

import numpy as np

Pair = tuple[Hashable, Hashable]


def _table(a: Sequence[Hashable], b: Sequence[Hashable], categories: Sequence[Hashable]) -> np.ndarray:
    """Construit la table de contingence de deux annotations."""
    if len(a) != len(b):
        raise ValueError("les deux annotations n'ont pas la même longueur")
    index = {c: i for i, c in enumerate(categories)}
    unknown = (set(a) | set(b)) - set(index)
    if unknown:
        raise ValueError(f"catégories inconnues : {sorted(map(str, unknown))}")
    table = np.zeros((len(categories), len(categories)))
    for x, y in zip(a, b, strict=True):
        table[index[x], index[y]] += 1
    return table


def _kappa(table: np.ndarray, weights: np.ndarray) -> float | None:
    """Calcule un kappa pondéré, ou None si l'accord attendu est total."""
    n = table.sum()
    if n == 0:
        return None
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / n
    denominator = float((weights * expected).sum())
    if denominator == 0:
        return None
    return 1.0 - float((weights * table).sum()) / denominator


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable], categories: Sequence[Hashable]) -> float | None:
    """Kappa non pondéré : poids 1 pour tout désaccord (forme équivalente à (po - pe) / (1 - pe))."""
    k = len(categories)
    return _kappa(_table(a, b, categories), 1.0 - np.eye(k))


def weighted_kappa(a: Sequence[Hashable], b: Sequence[Hashable], categories: Sequence[Hashable]) -> float | None:
    """Kappa pondéré linéairement ; `categories` dans leur ordre naturel (0, 1, 2)."""
    k = len(categories)
    if k < 2:
        raise ValueError("au moins deux catégories")
    i, j = np.indices((k, k))
    return _kappa(_table(a, b, categories), np.abs(i - j) / (k - 1))


def cluster_bootstrap_ci(clusters: Sequence[Sequence[Pair]],
                         statistic: Callable[[list, list], float | None], *, seed: int,
                         n_resamples: int = 10_000, alpha: float = 0.05) -> tuple[float | None, float | None]:
    """Calcule l'IC de `statistic` en tirant des réponses entières (grappes) ; (None, None) sans tirage valide."""
    if not clusters:
        return None, None
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for draw in rng.integers(0, len(clusters), size=(n_resamples, len(clusters))):
        pairs = [pair for c in draw for pair in clusters[c]]
        value = statistic([p[0] for p in pairs], [p[1] for p in pairs])
        if value is not None:
            values.append(value)
    if not values:
        return None, None
    return float(np.quantile(values, alpha / 2)), float(np.quantile(values, 1 - alpha / 2))
