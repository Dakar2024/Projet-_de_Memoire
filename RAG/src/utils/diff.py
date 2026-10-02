"""Écart entre le Gold (source de vérité) et l'index vectoriel d'un panel.

Fonctions pures : la décision « quoi recalculer, quoi supprimer » est la partie la
plus sensible de l'indexation, et elle se teste sans base ni service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from RAG.src.utils.errors import MassDeletionError


@dataclass(frozen=True)
class SyncPlan:
    to_delete: list[str]
    to_embed: list[str]
    unchanged: int


def plan_sync(
    gold: Mapping[str, str],
    indexed: Mapping[str, tuple[str, str]],
    fingerprint: str,
) -> SyncPlan:
    """`gold` : doc_id → chunk_id. `indexed` : doc_id → (chunk_id, embedding_model).

    Un document est à recalculer s'il est nouveau, si son texte a changé (chunk_id) ou
    s'il a été vectorisé par un autre modèle. Les listes sont triées : l'ordre des lots
    est ainsi reproductible d'une exécution à l'autre."""
    to_delete = sorted(set(indexed) - set(gold))
    to_embed = sorted(
        doc_id for doc_id, chunk in gold.items() if indexed.get(doc_id) != (chunk, fingerprint)
    )
    return SyncPlan(to_delete=to_delete, to_embed=to_embed, unchanged=len(gold) - len(to_embed))


def check_deletion_guard(
    plan: SyncPlan,
    gold_count: int,
    indexed_count: int,
    max_ratio: float,
    force: bool = False,
) -> None:
    """Refuse une indexation qui viderait l'index sur la foi d'un Gold incomplet.

    Un Gold vide est toujours refusé, même avec `force` : aucun mois légitime ne
    retire tous les variants d'un panel. `force` existe pour un retrait massif réel,
    constaté à la main, relancé explicitement."""
    if gold_count == 0:
        raise MassDeletionError(
            "le Gold de ce panel est vide : refus de vider l'index (lecture du lac incomplète ?)"
        )
    if force or indexed_count == 0:
        return
    ratio = len(plan.to_delete) / indexed_count
    if ratio > max_ratio:
        raise MassDeletionError(
            f"{len(plan.to_delete)} suppressions sur {indexed_count} documents indexés "
            f"({ratio:.1%} > {max_ratio:.0%}) : refus. Vérifier le Gold, puis relancer "
            "avec force_deletions=True si le retrait est réel."
        )
