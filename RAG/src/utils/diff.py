"""Écart entre le Gold et l'index d'un panel : quoi recalculer, quoi supprimer (fonctions pures)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from RAG.src.utils.errors import MassDeletionError


@dataclass(frozen=True)
class SyncPlan:
    """Documents à supprimer, à vectoriser, et nombre d'inchangés."""

    to_delete: list[str]
    to_embed: list[str]
    unchanged: int


def plan_sync(
    gold: Mapping[str, str],
    indexed: Mapping[str, tuple[str, str]],
    fingerprint: str,
) -> SyncPlan:
    """Planifie la synchronisation : recalcule le nouveau, le modifié ou l'issu d'un autre modèle (listes triées)."""
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
    """Refuse les suppressions massives (sauf `force`) et toujours un Gold vide."""
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
