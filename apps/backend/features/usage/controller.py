from litestar import Controller, get
from litestar.di import NamedDependency, Provide

from core.guards import active_user_guard, provide_current_user
from features.app_settings.service import get_settings
from features.assistant.schemas import UsageResponse
from features.auth.tables import User
from features.usage.service import quota_of


class UsageController(Controller):
    path = "/me/usage"
    tags = ["Me"]
    guards = [active_user_guard]
    dependencies = {"current_user": Provide(provide_current_user)}

    @get("/")
    async def my_usage(self, current_user: NamedDependency[User]) -> UsageResponse:
        quota = await quota_of(current_user, await get_settings())
        return UsageResponse(used=quota.used, limit=quota.limit, remaining=quota.remaining, resets_at=quota.resets_at)
