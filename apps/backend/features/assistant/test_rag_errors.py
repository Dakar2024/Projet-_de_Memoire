"""MODELISATION_BACKEND.md § 4.2, step 6: one case per row of the table."""

import pytest

from features.assistant.rag_errors import translate


def _json(code: str) -> dict:
    return {"error": code, "message": "…", "request_id": "abc"}


@pytest.mark.parametrize(
    ("status", "body", "headers", "code", "http", "retry_after"),
    [
        (422, _json("invalid_question"), {}, "validation_error", 422, None),
        (413, None, {}, "validation_error", 422, None),
        (429, _json("busy"), {}, "assistant_busy", 503, "2"),
        (429, None, {}, "assistant_busy", 503, "2"),  # nginx limit_req: HTML body
        (503, _json("timeout"), {}, "assistant_unavailable", 503, None),
        (503, _json("unavailable"), {"retry-after": "17"}, "assistant_unavailable", 503, "17"),
        (503, _json("index_empty"), {}, "index_building", 503, None),
        (502, None, {}, "assistant_unavailable", 503, None),  # rag-api down behind nginx
        (504, None, {}, "assistant_unavailable", 503, None),
        (500, _json("internal"), {}, "assistant_unavailable", 503, None),
        (401, _json("unauthorized"), {}, "internal", 500, None),  # our configuration, not the user
        (404, None, {}, "internal", 500, None),
    ],
)
def test_translation_table(status, body, headers, code, http, retry_after):
    error = translate(status, body, headers)
    assert (error.code, error.status) == (code, http)
    assert (error.headers or {}).get("Retry-After") == retry_after
    assert str(error)  # a message for humans


def test_wrong_api_key_is_logged(caplog: pytest.LogCaptureFixture):
    translate(401, _json("unauthorized"), {})
    assert "RAG_API_KEY" in caplog.text
