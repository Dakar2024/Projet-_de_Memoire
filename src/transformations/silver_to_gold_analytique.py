from __future__ import annotations

from transformations import SPEC


def silver_to_gold_analytique(
    logical_date: str, panel: str, lake_uri: str | None = None
) -> None:
    """Construit `gold/analytique/` (Delta) : modèle en étoile et agrégats.

    `fact_variant` et ses dimensions (gène, maladie, phénotype, signification
    clinique, temps). Agrégats : nombre de variants par gène et par signification,
    répartition des statuts de revue, reclassifications par mois. Lu par DuckDB pour
    l'application. Lit le Silver, jamais `gold/rag/`.

    Interdit : nettoyer. Le Silver est la seule couche qui nettoie ; une donnée qui
    arrive ici incorrecte se corrige dans `bronze_to_silver`, pas dans le Gold.
    """
    raise NotImplementedError(
        f"silver_to_gold_analytique : implémenté par le sous-projet D ({SPEC}, §7)"
    )
