"""Dans le conteneur rag-search (même image et mêmes réseaux que rag-api), contre la vraie
pile. Exclus de la passe rapide. Les tests du proxy sortent sur Internet (OpenRouter)."""

import os

import pytest
import requests

pytestmark = pytest.mark.integration


def test_proxy_refuses_a_domain_outside_the_allow_list():
    with pytest.raises(requests.exceptions.ProxyError):
        requests.get("https://example.com", timeout=15)


def test_proxy_lets_openrouter_through():
    assert requests.get("https://openrouter.ai/api/v1/models", timeout=30).status_code == 200


def test_direct_internet_access_is_impossible():
    session = requests.Session()
    session.trust_env = False
    with pytest.raises(requests.exceptions.ConnectionError):
        session.get("https://openrouter.ai/api/v1/models", timeout=10)


def test_api_answers_end_to_end():
    key = os.environ["RAG_API_KEY"]
    r = requests.post("http://rag-api:8000/v1/questions", headers={"X-API-Key": key},
                      json={"question": "Le variant rs80357906 sur BRCA1 est-il pathogène ?"}, timeout=180)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["status"] in ("answered", "partial") and any(s["doc_id"] == "clinvar:32716" for s in body["sources"])


def test_api_rejects_a_wrong_key():
    assert requests.post("http://rag-api:8000/v1/questions", headers={"X-API-Key": "faux"},
                         json={"question": "q ?"}, timeout=30).status_code == 401
