import asyncio

import httpx
import pytest

from core.settings import settings
from features.assistant.rag_client import RagClient, build_http_client
from features.assistant.rag_errors import AssistantError


def test_gateway_client_carries_the_key_and_a_longer_timeout(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "RAG_API_KEY", "secret-key")
    client = build_http_client()
    assert client.headers["x-api-key"] == "secret-key"
    assert client.timeout.read == settings.RAG_TIMEOUT_S > 130  # nginx gives up at 130 s
    assert str(client.base_url).rstrip("/") == settings.RAG_BASE_URL


def test_unexpected_answer_shape_is_an_internal_error():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "new-status"}))
    rag = RagClient(httpx.AsyncClient(transport=transport, base_url="http://rag"))
    with pytest.raises(AssistantError) as info:
        asyncio.run(rag.ask("question"))
    assert (info.value.code, info.value.status) == ("internal", 500)
