"""Journal JSON de l'API : champs autorisés seulement, jamais la question, la réponse ni la clé."""
from __future__ import annotations

import json
import logging
import sys

LOGGER = logging.getLogger("rag.api")
_ALLOWED = {"event", "request_id", "status", "http_status", "error", "timings_ms", "cost_usd", "model",
            "provider_name", "flags", "rejected", "scope_reason", "sources", "exception"}


def configure_logging() -> None:
    """Pose une seule fois le gestionnaire de `rag.api` sur la sortie standard."""
    LOGGER.setLevel(logging.INFO)
    if not any(getattr(h, "_rag_api", False) for h in LOGGER.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._rag_api = True
        LOGGER.addHandler(handler)


def log_event(**fields) -> None:
    """Écrit un événement en JSON, limité aux champs autorisés."""
    LOGGER.info(json.dumps({k: v for k, v in fields.items() if k in _ALLOWED}, ensure_ascii=False, default=str))
