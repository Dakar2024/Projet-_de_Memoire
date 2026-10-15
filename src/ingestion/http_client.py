"""Client HTTP NCBI E-utilities : relances, limitation de débit et masquage de la clé API."""
from __future__ import annotations

import time
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.config import EUTILS_BASE_URL, TOOL_NAME

# Erreurs transitoires relancées : un 429/5xx isolé ne doit pas perdre une collecte de ~1 200 appels.
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 3


class NcbiRequestError(RuntimeError):
    """Échec d'un appel E-utilities, dont le message (journalisé par Airflow) ne contient pas la clé API."""


def build_retrying_session() -> requests.Session:
    """Crée une session `requests` qui relance les erreurs transitoires (429/5xx) avec backoff."""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=frozenset(["GET"]),
        backoff_factor=1.0,
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class RateLimiter:
    """Espace les appels pour respecter la limite globale NCBI E-utilities."""

    def __init__(
        self,
        min_interval_seconds: float,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._sleep = sleep_fn
        self._now = time_fn
        self._last_call = None

    def wait(self) -> None:
        """Attend le temps restant depuis le dernier appel."""
        if self._last_call is not None:
            elapsed = self._now() - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_call = self._now()


class NcbiClient:
    """Client HTTP pour NCBI E-utilities (esearch/esummary), rate limité."""

    def __init__(
        self,
        email: str,
        api_key: str = "",
        rate_limiter: RateLimiter | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._email = email
        self._api_key = api_key
        self._rate_limiter = rate_limiter or RateLimiter(0.11 if api_key else 0.34)
        self._session = session or build_retrying_session()

    def _params(self, extra: dict) -> dict:
        # `tool` et `email` exigés par NCBI pour identifier l'appelant.
        params = {"tool": TOOL_NAME, "email": self._email, "retmode": "json", **extra}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def _mask(self, message: str) -> str:
        """Remplace la clé API par `***` partout où elle apparaît."""
        if not self._api_key:
            return message
        return message.replace(self._api_key, "***")

    def _get(self, endpoint: str, params: dict) -> requests.Response:
        """Appelle E-utilities en respectant le débit ; toute erreur est relevée sans la clé."""
        self._rate_limiter.wait()
        try:
            resp = self._session.get(
                f"{EUTILS_BASE_URL}/{endpoint}", params=self._params(params), timeout=30
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise NcbiRequestError(self._mask(str(exc))) from None
        return resp

    def esearch(self, db: str, term: str) -> list[str]:
        """Renvoie les UID correspondant à `term` dans la base `db`."""
        resp = self._get("esearch.fcgi", {"db": db, "term": term})
        return resp.json()["esearchresult"]["idlist"]

    def esummary(self, db: str, uid: str) -> dict:
        """Renvoie le résumé d'un UID de la base `db`."""
        resp = self._get("esummary.fcgi", {"db": db, "id": uid})
        return resp.json()["result"][uid]
