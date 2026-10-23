from typing import Annotated
from uuid import UUID

from litestar import Controller, Request, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, JSONBody, QueryParameter
from litestar.status_codes import HTTP_200_OK, HTTP_204_NO_CONTENT

from core.guards import active_user_guard, provide_current_user
from features.assistant.rag_client import RagClient
from features.assistant.schemas import (
    AskQuestionRequest,
    AskQuestionResponse,
    ConversationPage,
    ConversationResponse,
    ConversationSummary,
    FeedbackRequest,
    FeedbackResponse,
    UpdateConversationRequest,
)
from features.assistant.service import AssistantService
from features.auth.tables import User


def provide_assistant(request: Request) -> AssistantService:
    # One HTTP client for the process, opened at startup (app.py): connections to the gateway are reused.
    rag: RagClient = request.app.state.rag
    return AssistantService(rag)


class AssistantController(Controller):
    path = "/assistant"
    tags = ["Assistant"]
    guards = [active_user_guard]
    dependencies = {
        "assistant": Provide(provide_assistant, sync_to_thread=False),
        "current_user": Provide(provide_current_user),
    }

    @post("/questions", status_code=HTTP_200_OK)
    async def ask(
        self,
        data: JSONBody[AskQuestionRequest],
        current_user: NamedDependency[User],
        assistant: NamedDependency[AssistantService],
    ) -> AskQuestionResponse:
        return await assistant.ask(current_user, data)

    @get("/conversations")
    async def list_conversations(
        self,
        current_user: NamedDependency[User],
        assistant: NamedDependency[AssistantService],
        cursor: Annotated[str | None, QueryParameter(max_length=200)] = None,
        q: Annotated[str | None, QueryParameter(max_length=120)] = None,
    ) -> ConversationPage:
        return await assistant.list_conversations(current_user, cursor, q)

    @get("/conversations/{conversation_id:uuid}")
    async def get_conversation(
        self,
        conversation_id: FromPath[UUID],
        current_user: NamedDependency[User],
        assistant: NamedDependency[AssistantService],
    ) -> ConversationResponse:
        return await assistant.get_conversation(current_user, conversation_id)

    @patch("/conversations/{conversation_id:uuid}")
    async def update_conversation(
        self,
        conversation_id: FromPath[UUID],
        data: JSONBody[UpdateConversationRequest],
        current_user: NamedDependency[User],
        assistant: NamedDependency[AssistantService],
    ) -> ConversationSummary:
        return await assistant.update_conversation(current_user, conversation_id, data)

    @delete("/conversations/{conversation_id:uuid}", status_code=HTTP_204_NO_CONTENT)
    async def delete_conversation(
        self,
        conversation_id: FromPath[UUID],
        current_user: NamedDependency[User],
        assistant: NamedDependency[AssistantService],
    ) -> None:
        await assistant.delete_conversation(current_user, conversation_id)

    @put("/messages/{message_id:uuid}/feedback")
    async def set_feedback(
        self,
        message_id: FromPath[UUID],
        data: JSONBody[FeedbackRequest],
        current_user: NamedDependency[User],
        assistant: NamedDependency[AssistantService],
    ) -> FeedbackResponse:
        return await assistant.set_feedback(current_user, message_id, data)
