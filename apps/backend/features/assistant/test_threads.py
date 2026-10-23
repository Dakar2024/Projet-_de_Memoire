from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.exceptions import ValidationError
from features.assistant.threads import conversation_title, decode_cursor, encode_cursor, escape_like


def test_short_question_is_the_title():
    assert conversation_title("  Quelle est la\nsignification de c.68_69del ?  ") == (
        "Quelle est la signification de c.68_69del ?"
    )


def test_long_question_is_cut_at_60_characters():
    title = conversation_title("BRCA1 " * 30)
    assert len(title) == 60
    assert title.endswith("…")


def test_cursor_round_trip():
    stamp, conversation_id = datetime(2026, 10, 23, 1, 2, 3, 456789, tzinfo=UTC), uuid4()
    assert decode_cursor(encode_cursor(stamp, conversation_id)) == (stamp, conversation_id)


@pytest.mark.parametrize("cursor", ["", "garbage", "bm90LWEtZGF0ZXx4", encode_cursor(datetime(2026, 1, 1), uuid4())])
def test_bad_cursor_is_a_validation_error(cursor: str):
    with pytest.raises(ValidationError):
        decode_cursor(cursor)


def test_like_wildcards_are_escaped():
    assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"
