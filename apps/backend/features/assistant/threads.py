"""Small pure helpers for the conversation list: titles and pagination cursors."""

import base64
from datetime import datetime
from uuid import UUID

from core.exceptions import ValidationError

TITLE_MAX = 60


def conversation_title(question: str) -> str:
    """First ~60 characters of the first question, on one line (same rule as the frontend mock)."""
    flat = " ".join(question.split())
    return flat if len(flat) <= TITLE_MAX else f"{flat[: TITLE_MAX - 1].rstrip()}…"


def encode_cursor(updated_at: datetime, conversation_id: UUID) -> str:
    raw = f"{updated_at.isoformat()}|{conversation_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """Position after which the next page starts; a tampered cursor is a 422, not a 500."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, _, conversation_id = base64.urlsafe_b64decode(padded).decode().partition("|")
        updated_at = datetime.fromisoformat(stamp)
        if updated_at.tzinfo is None:
            raise ValueError("naive timestamp")
        return updated_at, UUID(conversation_id)
    except ValueError:
        raise ValidationError("Curseur de pagination invalide") from None


def escape_like(text: str) -> str:
    """Escape LIKE wildcards so a search for "50%" matches the characters, not a pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
