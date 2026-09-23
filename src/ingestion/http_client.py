from __future__ import annotations

import time
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.config import EUTILS_BASE_URL, TOOL_NAME

# Une collecte complète fait ~1 200 requêtes sur plusieurs minutes : un 429 ou un 5xx
# ponctuel côté NCBI ferait perdre tout le travail déjà accompli, rien n'étant écrit
# avant la toute fin du run.
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 3


class NcbiRequestError(RuntimeError):
    """Échec d'un appel E-utilities, message expurgé de la clé API.

    NCBI attend la clé en paramètre d'URL. Or le message d'une `HTTPError`
    reproduit l'URL complète, et Airflow journalise l'exception d'une tâche en
    échec : sans masquage, la clé finit en clair dans des logs conservés et
    consultables depuis l'interface web.
    """


def build_retrying_session() -> requests.Session:
    """Session `requests` avec retry/backoff sur les erreurs transitoires (429/5xx).

    Partagée par tous les clients HTTP du projet (NCBI E-utilities, API HPO) : une collecte
    complète fait des centaines d'appels sur plusieurs minutes, un 429/5xx ponctuel ne doit
    pas faire perdre le travail déjà accompli.
    """
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
        # NCBI demande `tool` et `email` pour identifier l'appelant : sans eux, un usage
        # jugé excessif est bloqué au lieu de donner lieu à une prise de contact.
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
        """Appel E-utilities rate-limité, dont toute erreur est relevée sans la clé.

        Le masquage porte sur le message, pas sur la requête : la clé doit bien
        partir chez NCBI, elle ne doit simplement jamais être journalisée.
        """
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
        resp = self._get("esearch.fcgi", {"db": db, "term": term})
        return resp.json()["esearchresult"]["idlist"]

    def esummary(self, db: str, uid: str) -> dict:
        resp = self._get("esummary.fcgi", {"db": db, "id": uid})
        return resp.json()["result"][uid]
