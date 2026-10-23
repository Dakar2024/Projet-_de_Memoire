"""Exchange schemas, same shapes as apps/frontend/src/shared/api/contracts.ts."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from core.schemas import CamelModel
from features.assistant.rag_client import AnswerStatus

PanelId = Literal["brca", "sickle"]

# Same bounds as the RAG `QuestionIn`: refused here, before spending a quota unit or a call.
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class AskQuestionRequest(CamelModel):
    conversation_id: UUID | None = None
    question:        Question
    panel:           PanelId | None = None


class SourceResponse(CamelModel):
    rank:                     int
    gene:                     str | None
    variant:                  str | None
    protein:                  str | None
    significance:             str | None
    significance_fr:          str | None
    review_status:            str | None
    stars:                    int | None
    clinvar_variation_id:     str | None
    clinvar_url:              str | None
    archive:                  str | None
    previous_significance_fr: str | None
    previous_until:           str | None


class UserMessageResponse(CamelModel):
    id:         UUID
    role:       Literal["user"] = "user"
    content:    str
    created_at: datetime


class AssistantMessageResponse(CamelModel):
    id:           UUID
    role:         Literal["assistant"] = "assistant"
    content:      str
    created_at:   datetime
    status:       AnswerStatus
    scope_reason: str | None
    history:      list[str]
    sources:      list[SourceResponse]
    disclaimer:   str


ChatMessage = Annotated[UserMessageResponse | AssistantMessageResponse, Field(discriminator="role")]


class AskQuestionResponse(CamelModel):
    conversation_id: UUID
    message:         AssistantMessageResponse
    quota_remaining: int
    # Admins only, and only when the admin_trace_visible setting is on: never the cost to a user.
    trace:           dict[str, Any] | None = None


class ConversationSummary(CamelModel):
    id:         UUID
    title:      str
    updated_at: datetime
    pinned:     bool


class ConversationPage(CamelModel):
    items:       list[ConversationSummary]
    next_cursor: str | None


class ConversationResponse(ConversationSummary):
    panel:    PanelId | None
    messages: list[ChatMessage]


class UpdateConversationRequest(CamelModel):
    title:  Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    pinned: bool | None = None


class FeedbackRequest(CamelModel):
    rating:  Literal[1, -1]
    comment: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class FeedbackResponse(CamelModel):
    rating:  Literal[1, -1]
    comment: str | None


class UsageResponse(CamelModel):
    used:      int
    limit:     int
    remaining: int
    resets_at: datetime
