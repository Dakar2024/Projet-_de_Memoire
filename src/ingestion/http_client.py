from __future__ import annotations

import time

import requests

from ingestion.config import EUTILS_BASE_URL


class RateLimiter:
    """Espace les appels pour respecter la limite globale NCBI E-utilities."""

    def __init__(self, min_interval_seconds, sleep_fn=time.sleep, time_fn=time.monotonic):
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

    def __init__(self, email, api_key="", rate_limiter=None, session=None):
        self._email = email
        self._api_key = api_key
        self._rate_limiter = rate_limiter or RateLimiter(0.11 if api_key else 0.34)
        self._session = session or requests.Session()

    def _params(self, extra: dict) -> dict:
        params = {"email": self._email, "retmode": "json", **extra}
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def esearch(self, db: str, term: str) -> list[str]:
        self._rate_limiter.wait()
        resp = self._session.get(
            f"{EUTILS_BASE_URL}/esearch.fcgi",
            params=self._params({"db": db, "term": term}),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["esearchresult"]["idlist"]

    def esummary(self, db: str, uid: str) -> dict:
        self._rate_limiter.wait()
        resp = self._session.get(
            f"{EUTILS_BASE_URL}/esummary.fcgi",
            params=self._params({"db": db, "id": uid}),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["result"][uid]
