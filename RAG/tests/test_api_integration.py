"""Dans le conteneur rag-api-test (image rag-api + pytest, mêmes réseaux que rag-api, y
compris rag-gateway-net pour joindre la passerelle), contre la vraie pile. Exclus de la
passe rapide. Les tests du proxy sortent sur Internet (OpenRouter)."""

import os

import pytest
import requests

pytestmark = pytest.mark.integration

# Adresse d'openrouter.ai résolue sur l'hôte le 08/10/2026 ; remplaçable par la variable.
OPENROUTER_IP = os.environ.get("RAG_TEST_OPENROUTER_IP", "104.18.2.115")


def test_proxy_refuses_a_domain_outside_the_allow_list():
    with pytest.raises(requests.exceptions.ProxyError):
        requests.get("https://example.com", timeout=15)


def test_proxy_lets_openrouter_through():
    assert requests.get("https://openrouter.ai/api/v1/models", timeout=30).status_code == 200


def test_proxy_refuses_an_allowed_host_on_another_port():
    with pytest.raises(requests.exceptions.ProxyError):
        requests.get("https://openrouter.ai:8443/api/v1/models", timeout=15)


def test_proxy_refuses_plain_http_even_to_an_allowed_host():
    # Sans CONNECT, Squid répond lui-même 403 (aucune erreur de tunnel côté requests).
    try:
        r = requests.get("http://openrouter.ai/api/v1/models", timeout=15)
    except requests.exceptions.ProxyError:
        return
    assert r.status_code == 403


def test_proxy_refuses_an_ip_literal_even_of_an_allowed_host():
    # Le refus ne dépend pas de l'adresse (acl to_ip) : une adresse d'OpenRouter, même
    # périmée, suffit. Le conteneur, sur des réseaux internes, ne résout aucun nom externe.
    with pytest.raises(requests.exceptions.ProxyError):
        requests.get(f"https://{OPENROUTER_IP}/api/v1/models", timeout=15, verify=False)


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


# Passerelle d'entrée (rag-gateway) : jointe par rag-gateway-net, sans proxy (NO_PROXY).
GATEWAY = "http://rag-gateway:8080"


def test_gateway_relays_health():
    assert requests.get(f"{GATEWAY}/health", timeout=15).status_code == 200


def test_gateway_does_not_relay_other_paths():
    # /schema n'est pas relayé : 404 de la passerelle, même avec une clé valable.
    r = requests.get(f"{GATEWAY}/schema", headers={"X-API-Key": os.environ["RAG_API_KEY"]}, timeout=15)
    assert r.status_code == 404


def test_gateway_relays_questions_and_the_api_checks_the_key():
    assert requests.post(f"{GATEWAY}/v1/questions", json={"question": "q ?"}, timeout=30).status_code == 401
