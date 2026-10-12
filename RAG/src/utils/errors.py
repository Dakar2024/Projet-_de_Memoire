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


class QuestionRejectedError(RagPermanentError):
    """Question vide ou trop longue : refusée avant tout appel réseau."""


class LlmPermanentError(RagPermanentError):
    """OpenRouter refuse la requête (clé, crédit, aucun point d'accès conforme)."""


class LlmUnavailableError(Exception):
    """OpenRouter injoignable, saturé ou réponse inexploitable : transitoire."""


class LlmQuotaExhaustedError(LlmUnavailableError):
    """Quota du fournisseur épuisé : inutile de réessayer avant sa réinitialisation. Une
    mesure s'arrête à la première occurrence au lieu d'attendre pour chaque question."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LlmProviderMismatchError(Exception):
    """La requête a été servie par un autre fournisseur que celui qui était figé."""


class LlmTruncatedError(LlmPermanentError):
    """Réponse coupée par le plafond de jetons, ou vide : relancer donnerait la même
    coupure, et la réponse a pourtant été facturée. `cost_usd` porte ce coût quand
    OpenRouter a pu le donner, `None` sinon."""

    def __init__(self, message: str, *, cost_usd: float | None = None) -> None:
        super().__init__(message)
        self.cost_usd = cost_usd


class GenerationRejectedError(Exception):
    """Réponse du LLM de génération refusée par un contrôle déterministe (citation ou
    identifiant hors des documents transmis, signification non sourcée). Interne : la
    réponse est remplacée par un message fixe, jamais livrée.

    Le message reste le code court. `detail` (diagnostic hors ligne uniquement) liste ce qui a
    déclenché le contrôle : identifiants, termes, phrase portant la négation."""

    def __init__(self, code: str, detail: list[str] | None = None) -> None:
        super().__init__(code)
        self.detail: list[str] = list(detail or [])
