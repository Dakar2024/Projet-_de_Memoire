"""Cohérence de docker-compose.yml avec la configuration du proxy et le cloisonnement des
secrets, vérifiée sans Docker : le fichier est lu comme du YAML (ancres et `<<` résolus)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
SQUID = (ROOT / "docker" / "rag-proxy" / "squid.conf").read_text(encoding="utf-8")
_VARIABLE = re.compile(r"\$\{([A-Z0-9_]+)")


def _environment(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, list):
        return dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return env


def _secrets_read_by(name: str) -> set[str]:
    """Variables du .env interpolées dans l'environnement d'un service."""
    return {var for value in _environment(SERVICES[name]).values() for var in _VARIABLE.findall(str(value))}


def test_squid_client_subnet_matches_the_proxy_network():
    subnets = [c["subnet"] for c in COMPOSE["networks"]["rag-proxy-net"]["ipam"]["config"]]
    acl = re.findall(r"^acl\s+rag_clients\s+src\s+(\S+)\s*$", SQUID, re.MULTILINE)
    assert len(subnets) == 1 and acl == subnets


def test_only_the_airflow_scheduler_sees_rag_secrets():
    airflow = [name for name in SERVICES if name.startswith("airflow")]
    assert "airflow-scheduler" in airflow and len(airflow) > 1
    for name in airflow:
        env = _environment(SERVICES[name])
        rag = {k for k in env if k.startswith("RAG_")} | {v for v in _secrets_read_by(name) if v.startswith("RAG_")}
        if name == "airflow-scheduler":
            assert {"RAG_INDEXER_PASSWORD", "RAG_EMBEDDINGS_API_KEY"} <= rag
            assert "rag-network" in SERVICES[name]["networks"]
        else:
            assert rag == set(), name
            assert "rag-network" not in (SERVICES[name].get("networks") or [])


def test_each_rag_secret_reaches_only_the_services_that_need_it():
    expected = {
        "RAG_OWNER_PASSWORD": {"rag-postgres", "rag-postgres-init"},
        "RAG_INDEXER_PASSWORD": {"rag-postgres-init", "airflow-scheduler"},
        "RAG_READER_PASSWORD": {"rag-postgres-init", "rag-api", "rag-search", "rag-api-test"},
        "RAG_API_KEY": {"rag-api", "rag-api-test"},
        "GROQ_API_KEY": {"rag-api", "rag-search"},
        "OPENROUTER_API_KEY": {"rag-api", "rag-search"},
    }
    for secret, services in expected.items():
        assert {name for name in SERVICES if secret in _secrets_read_by(name)} == services, secret


def test_the_gateway_and_the_proxy_hold_no_secret():
    for name in ("rag-gateway", "rag-proxy"):
        assert _secrets_read_by(name) == set(), name


def test_uvicorn_access_log_is_disabled():
    # Le journal JSON de l'API suffit ; celui d'uvicorn répéterait chaque requête.
    assert "--no-access-log" in SERVICES["rag-api"]["command"]
