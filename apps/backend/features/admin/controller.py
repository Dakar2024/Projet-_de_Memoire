from uuid import UUID

from litestar import Controller, get, post
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody
from litestar.status_codes import HTTP_200_OK

from core.guards import admin_guard, provide_current_user
from features.admin.service import AccessRequestService
from features.auth import controller as auth_controller
from features.auth.helpers import user_to_response
from features.auth.schemas import AccessRequestResponse, RejectRequest, UserResponse
from features.auth.tables import User


def provide_access_requests() -> AccessRequestService:
    return AccessRequestService(auth=auth_controller.provide_auth_service(), mailer=auth_controller.mailer_factory())


class AccessRequestController(Controller):
    path = "/admin/requests"
    tags = ["Admin"]
    guards = [admin_guard]
    dependencies = {
        "access_requests": Provide(provide_access_requests, sync_to_thread=False),
        "current_user": Provide(provide_current_user),
    }

    @get("/")
    async def list_requests(
        self, access_requests: NamedDependency[AccessRequestService]
    ) -> list[AccessRequestResponse]:
        return [AccessRequestResponse.model_validate(u.to_dict()) for u in await access_requests.pending()]

    @post("/{user_id:uuid}/approve", status_code=HTTP_200_OK)
    async def approve(
        self,
        user_id: FromPath[UUID],
        current_user: NamedDependency[User],
        access_requests: NamedDependency[AccessRequestService],
    ) -> UserResponse:
        return user_to_response(await access_requests.approve(current_user, user_id))

    @post("/{user_id:uuid}/reject", status_code=HTTP_200_OK)
    async def reject(
        self,
        user_id: FromPath[UUID],
        data: JSONBody[RejectRequest],
        current_user: NamedDependency[User],
        access_requests: NamedDependency[AccessRequestService],
    ) -> UserResponse:
        return user_to_response(await access_requests.reject(current_user, user_id, data.reason))
