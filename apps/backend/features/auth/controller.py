from collections.abc import Callable

from litestar import Controller, Request, Response, delete, get, patch, post, put
from litestar.datastructures import Cookie
from litestar.di import NamedDependency, Provide
from litestar.params import JSONBody
from litestar.status_codes import HTTP_200_OK, HTTP_202_ACCEPTED

from core.guards import (
    COOKIE_NAME,
    active_user_guard,
    onboarding_guard,
    provide_current_user,
    session_guard,
)
from core.redis import redis_client
from core.security import Limit, RateLimiter, RedisCounter, client_ip
from core.settings import settings
from features.auth.emails import Mailer
from features.auth.helpers import decode_token, session_lifetime, user_to_response
from features.auth.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    EmailRequest,
    LoginRequest,
    MessageResponse,
    OnboardingRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
    UpdateProfileRequest,
    UserResponse,
)
from features.auth.service import AuthService
from features.auth.status import AccountStatus
from features.auth.tables import User
from features.auth.tasks import HueyMailer

# (hits, window): per address against guessing one account, per IP against spraying many.
LOGIN_BY_EMAIL    = Limit("login-email", 10, 15 * 60)
LOGIN_BY_IP       = Limit("login-ip", 50, 15 * 60)
REGISTER_BY_EMAIL = Limit("register-email", 3, 60 * 60)
REGISTER_BY_IP    = Limit("register-ip", 10, 60 * 60)
MAIL_BY_EMAIL     = Limit("mail-email", 3, 60 * 60)  # forgot-password, resend-verification
MAIL_BY_IP        = Limit("mail-ip", 20, 60 * 60)
TOKEN_BY_IP       = Limit("token-ip", 30, 60 * 60)   # verify-email, reset-password

NEUTRAL_REGISTER = "Si cette adresse peut ouvrir un compte, un e-mail vient de lui être envoyé."
NEUTRAL_MAIL     = "Si un compte correspond à cette adresse, un e-mail vient de lui être envoyé."


# Module-level so the integration tests can swap in a mailer that records instead of sending.
mailer_factory: Callable[[], Mailer] = HueyMailer


def provide_auth_service() -> AuthService:
    return AuthService(mailer=mailer_factory())


def provide_rate_limiter() -> RateLimiter:
    return RateLimiter(RedisCounter(redis_client))


def session_cookie(token: str, *, remember: bool) -> Cookie:
    # No max_age without "remember me": a session cookie, dropped when the browser closes.
    max_age = int(session_lifetime(True).total_seconds()) if remember else None
    return Cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def cleared_cookie() -> Cookie:
    return Cookie(
        key=COOKIE_NAME,
        value="",
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        max_age=0,
        path="/",
    )


_DEPENDENCIES = {
    "auth_service": Provide(provide_auth_service, sync_to_thread=False),
    "rate_limiter": Provide(provide_rate_limiter, sync_to_thread=False),
    "current_user": Provide(provide_current_user),
}


class AuthController(Controller):
    path = "/auth"
    tags = ["Auth"]
    dependencies = _DEPENDENCIES

    @post("/register", status_code=HTTP_202_ACCEPTED)
    async def register(
        self,
        request: Request,
        data: JSONBody[RegisterRequest],
        auth_service: NamedDependency[AuthService],
        rate_limiter: NamedDependency[RateLimiter],
    ) -> MessageResponse:
        await rate_limiter.enforce(REGISTER_BY_IP, client_ip(request))
        await rate_limiter.enforce(REGISTER_BY_EMAIL, data.email)
        await auth_service.register(data)
        return MessageResponse(message=NEUTRAL_REGISTER)

    @post("/verify-email", status_code=HTTP_200_OK)
    async def verify_email(
        self,
        request: Request,
        data: JSONBody[TokenRequest],
        auth_service: NamedDependency[AuthService],
        rate_limiter: NamedDependency[RateLimiter],
    ) -> MessageResponse:
        await rate_limiter.enforce(TOKEN_BY_IP, client_ip(request))
        await auth_service.verify_email(data.token)
        return MessageResponse(message="Adresse confirmée. Connectez-vous pour compléter votre profil.")

    @post("/resend-verification", status_code=HTTP_202_ACCEPTED)
    async def resend_verification(
        self,
        request: Request,
        data: JSONBody[EmailRequest],
        auth_service: NamedDependency[AuthService],
        rate_limiter: NamedDependency[RateLimiter],
    ) -> MessageResponse:
        await rate_limiter.enforce(MAIL_BY_IP, client_ip(request))
        await rate_limiter.enforce(MAIL_BY_EMAIL, data.email)
        await auth_service.resend_verification(data.email)
        return MessageResponse(message=NEUTRAL_MAIL)

    @post("/login", status_code=HTTP_200_OK)
    async def login(
        self,
        request: Request,
        data: JSONBody[LoginRequest],
        auth_service: NamedDependency[AuthService],
        rate_limiter: NamedDependency[RateLimiter],
    ) -> Response[UserResponse]:
        await rate_limiter.enforce(LOGIN_BY_IP, client_ip(request))
        await rate_limiter.enforce(LOGIN_BY_EMAIL, data.email)
        user, token = await auth_service.login(data)
        return Response(content=user_to_response(user), cookies=[session_cookie(token, remember=data.remember)])

    @delete("/logout", status_code=HTTP_200_OK)
    async def logout(self) -> Response[MessageResponse]:
        return Response(content=MessageResponse(message="Déconnecté"), cookies=[cleared_cookie()])

    @get("/me", guards=[session_guard])
    async def me(self, current_user: NamedDependency[User]) -> UserResponse:
        return user_to_response(current_user)

    @patch("/me", guards=[active_user_guard])
    async def update_profile(
        self,
        data: JSONBody[UpdateProfileRequest],
        current_user: NamedDependency[User],
        auth_service: NamedDependency[AuthService],
    ) -> UserResponse:
        return user_to_response(await auth_service.update_profile(current_user, data))

    @patch("/me/password", guards=[active_user_guard])
    async def change_password(
        self,
        request: Request,
        data: JSONBody[ChangePasswordRequest],
        current_user: NamedDependency[User],
        auth_service: NamedDependency[AuthService],
    ) -> Response[MessageResponse]:
        remember = decode_token(request.cookies[COOKIE_NAME]).remember
        token = await auth_service.change_password(current_user, data, remember=remember)
        return Response(
            content=MessageResponse(message="Mot de passe mis à jour. Les autres sessions sont fermées."),
            cookies=[session_cookie(token, remember=remember)],
        )

    @post("/forgot-password", status_code=HTTP_202_ACCEPTED)
    async def forgot_password(
        self,
        request: Request,
        data: JSONBody[EmailRequest],
        auth_service: NamedDependency[AuthService],
        rate_limiter: NamedDependency[RateLimiter],
    ) -> MessageResponse:
        await rate_limiter.enforce(MAIL_BY_IP, client_ip(request))
        await rate_limiter.enforce(MAIL_BY_EMAIL, data.email)
        await auth_service.forgot_password(data.email)
        return MessageResponse(message=NEUTRAL_MAIL)

    @post("/reset-password", status_code=HTTP_200_OK)
    async def reset_password(
        self,
        request: Request,
        data: JSONBody[ResetPasswordRequest],
        auth_service: NamedDependency[AuthService],
        rate_limiter: NamedDependency[RateLimiter],
    ) -> MessageResponse:
        await rate_limiter.enforce(TOKEN_BY_IP, client_ip(request))
        await auth_service.reset_password(data.token, data.password)
        return MessageResponse(message="Mot de passe réinitialisé. Vous pouvez vous connecter.")


class MeController(Controller):
    path = "/me"
    tags = ["Me"]
    dependencies = _DEPENDENCIES

    @put("/onboarding", guards=[onboarding_guard])
    async def complete_onboarding(
        self,
        data: JSONBody[OnboardingRequest],
        current_user: NamedDependency[User],
        auth_service: NamedDependency[AuthService],
    ) -> Response[UserResponse]:
        user = await auth_service.complete_onboarding(current_user, data)
        # Waiting for review: the session ends here, the frontend shows the pending screen.
        cookies = [] if user.status == AccountStatus.ACTIVE else [cleared_cookie()]
        return Response(content=user_to_response(user), cookies=cookies)

    @delete("/", guards=[session_guard], status_code=HTTP_200_OK)
    async def delete_account(
        self,
        data: JSONBody[DeleteAccountRequest],
        current_user: NamedDependency[User],
        auth_service: NamedDependency[AuthService],
    ) -> Response[MessageResponse]:
        await auth_service.delete_account(current_user, data.password)
        return Response(
            content=MessageResponse(message="Compte et historique supprimés."), cookies=[cleared_cookie()]
        )
