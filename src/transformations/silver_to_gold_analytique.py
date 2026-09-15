from __future__ import annotations

from transformations.raw_to_bronze import SPEC


def silver_to_gold_analytique(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/analytique/` (Delta) : modèle en étoile et agrégats.

    `fact_variant` et ses dimensions (gène, maladie, phénotype, signification
    clinique, temps) ; agrégats par gène, par signification et reclassifications
    par mois. Lu par DuckDB pour l'application. Lit le Silver, jamais `gold/rag/`.
    """
    raise NotImplementedError(
        f"silver_to_gold_analytique : implémenté par le sous-projet D ({SPEC}, §7)"
    )
