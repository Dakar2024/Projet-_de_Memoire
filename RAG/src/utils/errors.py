"""Erreurs du RAG, classées selon qu'une relance peut ou non les corriger.

La tâche Airflow traduit `RagPermanentError` en `AirflowFailException` : relancer
ne changerait rien (mauvais modèle, document trop long, configuration absente), et
consommer trois relances retarderait seulement le diagnostic. Les autres erreurs
sont transitoires : Airflow relance, et la reprise ne refait que le travail manquant.
"""

from __future__ import annotations


class RagPermanentError(Exception):
    """Une relance ne corrigera pas cette erreur."""


class RagConfigurationError(RagPermanentError):
    """Configuration absente ou invalide (`config.yaml`, variables d'environnement)."""


class DocumentTooLongError(RagPermanentError):
    """Un document dépasse la fenêtre du modèle : il serait vectorisé amputé."""


class CanaryMismatchError(RagPermanentError):
    """Le modèle servi n'est pas celui que l'index attend."""


class MassDeletionError(RagPermanentError):
    """L'indexation supprimerait une part anormale de l'index."""


class EmbeddingRequestError(RagPermanentError):
    """Requête refusée par le service d'embedding (authentification, validation)."""


class EmbeddingServiceError(Exception):
    """Service d'embedding injoignable, saturé ou en erreur serveur : transitoire."""


class IndexLockedError(Exception):
    """Une autre indexation du même panel est en cours."""


class IndexConsistencyError(Exception):
    """Après indexation, l'index ne reflète pas exactement le Gold."""
