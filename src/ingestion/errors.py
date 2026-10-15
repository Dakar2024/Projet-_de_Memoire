"""Erreurs métier pour l'ingestion."""
from __future__ import annotations


class ConfigurationError(RuntimeError):
    """Erreur permanente : la relancer ne peut pas la résoudre.

    Levée quand une variable d'environnement obligatoire manque. Vit dans
    `ingestion` et non dans `scripts` parce que les DAGs doivent l'attraper pour
    la convertir en échec Airflow non-retenté, sans dépendre d'un point d'entrée CLI.
    """
