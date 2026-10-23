"""Assistant: ask the RAG, keep the history (MODELISATION_BACKEND.md § 4.2)."""

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from core.exceptions import NotFoundError, ValidationError
from features.app_settings.service import get_settings
from features.assistant.rag_client import RagAnswer, RagClient
from features.assistant.rag_errors import AssistantError
from features.assistant.review_stars import stars_for
from features.assistant.schemas import (
    AskQuestionRequest,
    AskQuestionResponse,
    AssistantMessageResponse,
    ConversationPage,
    ConversationResponse,
    ConversationSummary,
    FeedbackRequest,
    FeedbackResponse,
    SourceResponse,
    UpdateConversationRequest,
    UserMessageResponse,
)
from features.assistant.tables import Conversation, Feedback, Message, MessageSource
from features.assistant.threads import conversation_title, decode_cursor, encode_cursor, escape_like
from features.auth.tables import User
from features.usage import service as usage
from features.usage.tables import UsageEvent

PAGE_SIZE = 30


class ConversationNotFoundError(NotFoundError):
    def __init__(self) -> None:
        # Same answer for "absent" and "someone else's": existence is not revealed.
        super().__init__("Conversation introuvable")


class PanelFilterUnavailableError(ValidationError):
    code = "panel_filter_unavailable"

    def __init__(self) -> None:
        super().__init__("Le filtre par panel n'est pas encore disponible dans l'assistant.")


def _now() -> datetime:
    return datetime.now(UTC)


def _owned(user: User):
    """Conversations of this user still visible: every read and write goes through this filter."""
    return (Conversation.user == user.id) & Conversation.deleted_at.is_null()


class AssistantService:
    def __init__(self, rag: RagClient) -> None:
        self._rag = rag

    # ── Ask ──────────────────────────────────────────────────────────────────

    async def ask(self, user: User, data: AskQuestionRequest) -> AskQuestionResponse:
        if data.panel is not None:
            # No decorative filter: the RAG cannot restrict its search to a panel yet (§ 4.2).
            raise PanelFilterUnavailableError()
        conversation = await self._get_owned(user, data.conversation_id) if data.conversation_id else None

        config = await get_settings()
        await usage.ensure_budget(config)
        day = usage.today()
        limit = usage.daily_limit(user, config)
        used = await usage.reserve(user.id, day, limit)

        asked_at = _now()
        started = time.perf_counter()
        try:
            answer = await self._rag.ask(data.question)
        except AssistantError as error:
            await usage.release(user.id, day)
            await UsageEvent(
                user=user.id,
                http_status=error.status,
                error_code=error.code,
                latency_ms=round((time.perf_counter() - started) * 1000),
            ).save().run()
            raise
        latency_ms = round((time.perf_counter() - started) * 1000)

        # Question and answer are written together, after the answer: a failed call leaves no
        # orphan question in the thread (the frontend keeps it in the composer).
        async with Conversation._meta.db.transaction():
            answered_at = _now()
            if conversation is None:
                conversation = Conversation(
                    user=user.id, title=conversation_title(data.question), updated_at=answered_at
                )
                await conversation.save().run()
            else:
                await Conversation.update({Conversation.updated_at: answered_at}).where(
                    Conversation.id == conversation.id
                ).run()
            question = Message(conversation=conversation.id, role="user", content=data.question, created_at=asked_at)
            await question.save().run()
            reply = await self._save_answer(conversation.id, answer, answered_at)
            await UsageEvent(
                user=user.id,
                message=reply.id,
                status=answer.status,
                http_status=200,
                cost_usd=Decimal(str(answer.cost_usd)) if answer.cost_usd is not None else None,
                model=answer.model,
                provider_name=answer.provider_name,
                latency_ms=latency_ms,
                rag_request_id=answer.request_id,
            ).save().run()

        show_trace = user.role == "admin" and config.admin_trace_visible
        return AskQuestionResponse(
            conversation_id=conversation.id,
            message=await self._assistant_message(reply),
            quota_remaining=max(limit - used, 0),
            trace=answer.trace if show_trace else None,
        )

    async def _save_answer(self, conversation_id: UUID, answer: RagAnswer, at: datetime) -> Message:
        reply = Message(
            conversation=conversation_id,
            role="assistant",
            content=answer.answer,
            status=answer.status,
            scope_reason=answer.scope_reason,
            history=answer.history,
            disclaimer=answer.disclaimer,
            rag_request_id=answer.request_id,
            timings_ms=answer.timings_ms,
            archive=next((s.archive for s in answer.sources if s.archive), None),
            created_at=at,
        )
        await reply.save().run()
        if answer.sources:
            # Frozen copy, in citation order: the thread must show what was answered, with that archive.
            await MessageSource.insert(
                *(MessageSource(message=reply.id, rank=rank, **source.model_dump())
                  for rank, source in enumerate(answer.sources, start=1))
            ).run()
        return reply

    # ── History ──────────────────────────────────────────────────────────────

    async def list_conversations(self, user: User, cursor: str | None, q: str | None) -> ConversationPage:
        where = _owned(user)
        if q and q.strip():
            where &= Conversation.title.ilike(f"%{escape_like(q.strip())}%")
        if cursor:
            updated_at, last_id = decode_cursor(cursor)
            # Keyset pagination on (updated_at, id), newest first: stable while new questions arrive.
            where &= (Conversation.updated_at < updated_at) | (
                (Conversation.updated_at == updated_at) & (Conversation.id < last_id)
            )
        rows = await (
            Conversation.select(Conversation.id, Conversation.title, Conversation.updated_at, Conversation.pinned)
            .where(where)
            .order_by(Conversation.updated_at, Conversation.id, ascending=False)
            .limit(PAGE_SIZE + 1)
            .run()
        )
        page, more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
        return ConversationPage(
            items=[ConversationSummary.model_validate(row) for row in page],
            next_cursor=encode_cursor(page[-1]["updated_at"], page[-1]["id"]) if more else None,
        )

    async def get_conversation(self, user: User, conversation_id: UUID) -> ConversationResponse:
        conversation = await self._get_owned(user, conversation_id)
        messages = await (
            Message.objects()
            .where(Message.conversation == conversation.id)
            .order_by(Message.created_at, Message.id)
            .run()
        )
        sources = await self._sources_by_message([m.id for m in messages if m.role == "assistant"])
        return ConversationResponse(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at,
            pinned=conversation.pinned,
            panel=conversation.panel,
            messages=[
                UserMessageResponse(id=m.id, content=m.content, created_at=m.created_at)
                if m.role == "user"
                else self._to_response(m, sources.get(m.id, []))
                for m in messages
            ],
        )

    async def update_conversation(
        self, user: User, conversation_id: UUID, data: UpdateConversationRequest
    ) -> ConversationSummary:
        conversation = await self._get_owned(user, conversation_id)
        changes: dict[Any, Any] = {}
        if data.title is not None:
            changes[Conversation.title] = data.title
        if data.pinned is not None:
            changes[Conversation.pinned] = data.pinned
        if changes:
            await Conversation.update(changes).where(Conversation.id == conversation.id).run()
        conversation = await self._get_owned(user, conversation_id)
        return ConversationSummary(
            id=conversation.id, title=conversation.title, updated_at=conversation.updated_at, pinned=conversation.pinned
        )

    async def delete_conversation(self, user: User, conversation_id: UUID) -> None:
        updated = (
            await Conversation.update({Conversation.deleted_at: _now()})
            .where(_owned(user) & (Conversation.id == conversation_id))
            .returning(Conversation.id)
            .run()
        )
        if not updated:
            raise ConversationNotFoundError()

    async def set_feedback(self, user: User, message_id: UUID, data: FeedbackRequest) -> FeedbackResponse:
        message = await (
            Message.objects()
            .where(
                (Message.id == message_id)
                & (Message.role == "assistant")
                & (Message.conversation.user == user.id)
                & Message.conversation.deleted_at.is_null()
            )
            .first()
        )
        if message is None:
            raise NotFoundError("Message introuvable")
        await Feedback.insert(Feedback(message=message.id, rating=data.rating, comment=data.comment)).on_conflict(
            target=Feedback.message,
            action="DO UPDATE",
            values=[Feedback.rating, Feedback.comment, Feedback.updated_at],
        ).run()
        return FeedbackResponse(rating=data.rating, comment=data.comment)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _get_owned(self, user: User, conversation_id: UUID) -> Conversation:
        conversation = await Conversation.objects().where(_owned(user) & (Conversation.id == conversation_id)).first()
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    async def _sources_by_message(self, message_ids: list[UUID]) -> dict[UUID, list[MessageSource]]:
        if not message_ids:
            return {}
        rows = await (
            MessageSource.objects()
            .where(MessageSource.message.is_in(message_ids))
            .order_by(MessageSource.rank)
            .run()
        )
        grouped: dict[UUID, list[MessageSource]] = {}
        for row in rows:
            grouped.setdefault(row.message, []).append(row)
        return grouped

    async def _assistant_message(self, message: Message) -> AssistantMessageResponse:
        return self._to_response(message, (await self._sources_by_message([message.id])).get(message.id, []))

    @staticmethod
    def _to_response(message: Message, sources: list[MessageSource]) -> AssistantMessageResponse:
        return AssistantMessageResponse(
            id=message.id,
            content=message.content,
            created_at=message.created_at,
            status=message.status,
            scope_reason=message.scope_reason,
            history=_json_list(message.history),
            disclaimer=message.disclaimer or "",
            sources=[
                SourceResponse(
                    rank=s.rank,
                    gene=s.gene,
                    variant=s.variant,
                    protein=s.protein,
                    significance=s.significance,
                    significance_fr=s.significance_fr,
                    review_status=s.review_status,
                    stars=stars_for(s.review_status),
                    clinvar_variation_id=s.clinvar_variation_id,
                    clinvar_url=s.clinvar_url,
                    archive=s.archive,
                    previous_significance_fr=s.previous_significance_fr,
                    previous_until=s.previous_until,
                )
                for s in sources
            ],
        )


def _json_list(value: Any) -> list[str]:
    """Piccolo returns JSONB as text on objects() queries."""
    if value is None:
        return []
    if isinstance(value, str):
        return list(json.loads(value))
    return list(value)
