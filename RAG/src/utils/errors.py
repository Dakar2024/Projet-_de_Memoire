"""Erreurs du RAG : `RagPermanentError` n'est pas relancée par Airflow, les autres sont transitoires."""
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


class IndexEmptyError(Exception):
    """Index encore vide (installation neuve, avant la première indexation) : transitoire."""


class IndexConsistencyError(Exception):
    """Après indexation, l'index ne reflète pas exactement le Gold."""


class QuestionRejectedError(RagPermanentError):
    """Question vide ou trop longue : refusée avant tout appel réseau."""


class LlmPermanentError(RagPermanentError):
    """OpenRouter refuse la requête (clé, crédit, aucun point d'accès conforme)."""


class LlmUnavailableError(Exception):
    """OpenRouter injoignable, saturé ou réponse inexploitable : transitoire."""


class LlmQuotaExhaustedError(LlmUnavailableError):
    """Quota du fournisseur épuisé : inutile de réessayer avant sa réinitialisation."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LlmProviderMismatchError(Exception):
    """La requête a été servie par un autre fournisseur que celui qui était figé."""


class LlmTruncatedError(LlmPermanentError):
    """Réponse vide ou coupée par le plafond de jetons, mais facturée (`cost_usd` si connu)."""

    def __init__(self, message: str, *, cost_usd: float | None = None) -> None:
        super().__init__(message)
        self.cost_usd = cost_usd


class GenerationRejectedError(Exception):
    """Réponse refusée par un contrôle déterministe, jamais livrée ; `detail` sert au diagnostic hors ligne."""

    def __init__(self, code: str, detail: list[str] | None = None) -> None:
        super().__init__(code)
        self.detail: list[str] = list(detail or [])
