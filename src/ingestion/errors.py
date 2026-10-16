"""Erreurs métier pour l'ingestion."""
from __future__ import annotations


class ConfigurationError(RuntimeError):
    """Erreur permanente de configuration, que les DAGs ne relancent pas."""


class SourceSchemaError(RuntimeError):
    """Colonnes d'une source différentes du schéma attendu : permanente, une relance relirait le même fichier."""
