from core.exceptions import AlreadyExistsError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationError
from features.auth.status import AccountStatus


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Email ou mot de passe invalide")


class AccountBlockedError(ForbiddenError):
    """Correct password, but the account cannot sign in yet (or any more)."""

    _MESSAGES = {
        AccountStatus.PENDING_EMAIL:  "Confirmez d'abord votre adresse avec le lien reçu par e-mail.",
        AccountStatus.PENDING_REVIEW: "Votre demande d'accès est en cours d'examen.",
        AccountStatus.REJECTED:       "Votre demande d'accès n'a pas été acceptée.",
        AccountStatus.SUSPENDED:      "Ce compte est suspendu.",
    }

    def __init__(self, status: AccountStatus) -> None:
        self.code = f"account_{status.value}"
        super().__init__(self._MESSAGES.get(status, "Compte indisponible."))


class EmailNotProfessionalError(ValidationError):
    code = "email_not_professional"

    def __init__(self) -> None:
        super().__init__("Utilisez l'adresse e-mail de votre établissement.")


class RegistrationClosedError(ForbiddenError):
    code = "registration_closed"

    def __init__(self) -> None:
        super().__init__("Les inscriptions sont fermées.")


class InvalidTokenError(ValidationError):
    code = "invalid_token"

    def __init__(self) -> None:
        super().__init__("Lien invalide ou expiré.")


class LastAdminError(AlreadyExistsError):
    code = "last_admin"

    def __init__(self) -> None:
        super().__init__("Impossible : c'est le dernier administrateur actif.")


class UserNotFoundError(NotFoundError):
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Utilisateur '{identifier}' introuvable")
