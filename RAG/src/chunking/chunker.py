"""Contrôle de longueur des documents, sans découpage.

Aucun document du Gold n'a besoin d'être découpé : le plus long fait 257 tokens pour
une fenêtre de 512 (mesure du 30/09/2026 sur les 96 910 documents). Ce module le
vérifie à chaque indexation plutôt que de le supposer : un gabarit Gold allongé
produirait sinon des vecteurs de documents amputés. Le comptage passe par le
tokenizer du modèle servi, pas par une estimation en caractères.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from RAG.src.utils.errors import DocumentTooLongError

_MAX_NAMED = 20


def check_token_lengths(
    doc_ids: Sequence[str],
    texts: Sequence[str],
    token_counts: Callable[[Sequence[str]], list[int]],
    max_tokens: int,
) -> None:
    if len(doc_ids) != len(texts):
        raise ValueError(f"{len(doc_ids)} identifiants pour {len(texts)} textes")
    counts = token_counts(texts)
    too_long = [(doc_id, n) for doc_id, n in zip(doc_ids, counts, strict=True) if n > max_tokens]
    if too_long:
        named = ", ".join(f"{doc_id} ({n})" for doc_id, n in too_long[:_MAX_NAMED])
        raise DocumentTooLongError(
            f"{len(too_long)} document(s) au-delà de {max_tokens} tokens : {named}"
        )
