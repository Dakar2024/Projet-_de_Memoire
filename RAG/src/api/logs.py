"""Journal de l'API : une ligne JSON par événement, sur la sortie standard. Seuls des
champs choisis y entrent ; jamais le texte de la question, de la réponse, ni la clé."""

from __future__ import annotations

import json
import logging
import sys

LOGGER = logging.getLogger("rag.api")
_ALLOWED = {"event", "request_id", "status", "http_status", "error", "timings_ms", "cost_usd", "model",
            "provider_name", "flags", "rejected", "scope_reason", "sources", "exception"}


def configure_logging() -> None:
    """Un gestionnaire sur la sortie standard pour `rag.api`, posé une seule fois. Litestar ne
    configure pas la journalisation (`logging_config=None`) : il ne touche pas au journal racine
    et ne journalise aucune trace d'exception (qui pourrait citer la requête)."""
    LOGGER.setLevel(logging.INFO)
    if not any(getattr(h, "_rag_api", False) for h in LOGGER.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._rag_api = True
        LOGGER.addHandler(handler)


def log_event(**fields) -> None:
    LOGGER.info(json.dumps({k: v for k, v in fields.items() if k in _ALLOWED}, ensure_ascii=False, default=str))
