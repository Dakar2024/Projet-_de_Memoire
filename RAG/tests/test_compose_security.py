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


def _nginx_size(value: str) -> int:
    """Taille nginx (« 8k », « 1m », « 8192 ») en octets."""
    number, unit = re.fullmatch(r"(\d+)([kKmM]?)", value).groups()
    return int(number) * {"": 1, "k": 1024, "m": 1024 * 1024}[unit.lower()]


def test_gateway_body_limit_matches_the_api_limit():
    """Revue finale n° 2, m6 : le plafond de corps de la passerelle et celui de l'API
    (api.max_body_bytes) doivent rester égaux ; seul un commentaire les liait."""
    nginx = (ROOT / "docker" / "rag-gateway" / "nginx.conf").read_text(encoding="utf-8")
    api = yaml.safe_load((ROOT / "RAG" / "config.yaml").read_text(encoding="utf-8"))["api"]["max_body_bytes"]
    sizes = {name: [_nginx_size(v) for v in re.findall(rf"^\s*{name}\s+(\S+);", nginx, re.MULTILINE)]
             for name in ("client_max_body_size", "client_body_buffer_size")}
    assert sizes == {"client_max_body_size": [api], "client_body_buffer_size": [api]}
    assert _nginx_size("8k") == 8192 and _nginx_size("1M") == 1048576


def _seconds(value: str) -> int:
    """Durée Compose simple (« 250s », « 4m10s ») en secondes."""
    parts = re.fullmatch(r"(?:(\d+)m)?(?:(\d+)s)?", value)
    assert parts and value, value
    return int(parts.group(1) or 0) * 60 + int(parts.group(2) or 0)


def test_api_stop_grace_period_covers_the_shutdown_wait():
    """Re-relecture de la vague n° 2, N7 : à l'arrêt, uvicorn laisse finir les requêtes en cours
    (chacune bornée par api.request_timeout_s), puis le lifespan attend les fils actifs au plus
    request_timeout_s avant de fermer les connexions. Sans délai suffisant, Docker tue le
    processus au bout de 10 s (SIGKILL) et cette attente n'a jamais lieu."""
    timeout = yaml.safe_load((ROOT / "RAG" / "config.yaml").read_text(encoding="utf-8"))["api"]["request_timeout_s"]
    assert _seconds(SERVICES["rag-api"]["stop_grace_period"]) >= 2 * timeout + 5
