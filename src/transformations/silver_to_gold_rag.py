from __future__ import annotations

from transformations.raw_to_bronze import SPEC


def silver_to_gold_rag(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/rag/` (Delta) : un document par variant pour le RAG.

    Chaque document porte le contexte du gène, des maladies et des phénotypes, et ses
    références de citation (accession ClinVar, version, date de collecte).
    `chunk_id` est un hash déterministe du contenu, pour ne ré-embedder par `MERGE`
    que les documents modifiés. Lit le Silver, jamais `gold/analytique/`.
    """
    raise NotImplementedError(f"silver_to_gold_rag : implémenté par le sous-projet D ({SPEC}, §7)")
