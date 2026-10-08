import json

import numpy as np
import pytest
import requests
import responses

from RAG.src.embeddings.embedder import EMBEDDING_DIM, EmbeddingClient
from RAG.src.utils.errors import EmbeddingRequestError, EmbeddingServiceError

URL = "http://rag-embeddings:8080"


def _client() -> EmbeddingClient:
    # Session sans relance : les tests vérifient le classement des erreurs, pas l'attente.
    return EmbeddingClient(URL, "cle-secrete", session=requests.Session())


@responses.activate
def test_embed_sends_the_key_and_refuses_silent_truncation():
    responses.add(responses.POST, f"{URL}/embed", json=[[0.1] * EMBEDDING_DIM] * 2)

    vectors = _client().embed(["BRCA1", "BRCA2"])

    assert vectors.shape == (2, EMBEDDING_DIM)
    assert vectors.dtype == np.float32
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer cle-secrete"
    assert json.loads(request.body) == {"inputs": ["BRCA1", "BRCA2"], "truncate": False, "normalize": True}


def test_embed_refuses_more_than_the_service_batch_limit():
    with pytest.raises(ValueError, match="32"):
        _client().embed(["x"] * 33)


@responses.activate
def test_a_wrong_vector_shape_is_detected():
    responses.add(responses.POST, f"{URL}/embed", json=[[0.1] * 10])

    with pytest.raises(EmbeddingServiceError, match="forme"):
        _client().embed(["x"])


@responses.activate
@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_are_permanent(status):
    responses.add(responses.POST, f"{URL}/embed", status=status)

    with pytest.raises(EmbeddingRequestError, match="RAG_EMBEDDINGS_API_KEY"):
        _client().embed(["x"])


@responses.activate
def test_validation_errors_are_permanent_and_quote_the_service():
    responses.add(responses.POST, f"{URL}/embed", status=422,
                  json={"error": "`inputs` must have less than 512 tokens. Given: 702"})

    with pytest.raises(EmbeddingRequestError, match="702"):
        _client().embed(["x"])


@responses.activate
@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_errors_and_throttling_are_transient(status):
    responses.add(responses.POST, f"{URL}/embed", status=status)

    with pytest.raises(EmbeddingServiceError):
        _client().embed(["x"])


@responses.activate
def test_an_unreachable_service_is_transient():
    responses.add(responses.POST, f"{URL}/embed", body=requests.ConnectionError("refusé"))

    with pytest.raises(EmbeddingServiceError, match="injoignable"):
        _client().embed(["x"])


@responses.activate
def test_token_counts_batches_by_32_and_counts_special_tokens():
    def tokenize(request):
        inputs = json.loads(request.body)["inputs"]
        assert len(inputs) <= 32
        assert json.loads(request.body)["add_special_tokens"] is True
        return 200, {}, json.dumps([[{"id": 1}] * (len(text) + 2) for text in inputs])

    responses.add_callback(responses.POST, f"{URL}/tokenize", callback=tokenize)

    counts = _client().token_counts(["ab"] * 40)

    assert counts == [4] * 40
    assert len(responses.calls) == 2


@responses.activate
def test_max_input_length_comes_from_the_service():
    responses.add(responses.GET, f"{URL}/info", json={"max_input_length": 512})

    assert _client().max_input_length() == 512


def test_an_empty_api_key_is_refused_upfront():
    with pytest.raises(EmbeddingRequestError):
        EmbeddingClient(URL, "")


def test_close_closes_the_session():
    closed = []

    class Session:
        def close(self):
            closed.append(1)

    EmbeddingClient(URL, "cle-secrete", session=Session()).close()

    assert closed == [1]
