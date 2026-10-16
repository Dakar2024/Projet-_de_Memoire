"""Ouverture de `PgVectorStore` sans base : délais posés, connexion fermée si l'amorçage échoue."""
from __future__ import annotations

import pytest

from RAG.src.vectordb import vector_store


class _FakeConnection:
    """Connexion psycopg factice qui journalise les requêtes et sa fermeture."""

    def __init__(self) -> None:
        self.closed = False
        self.executed: list[tuple[str, tuple]] = []
        self.calls: list[dict] = []

    def execute(self, query: str, params: tuple = ()) -> _FakeConnection:
        self.executed.append((query, params))
        return self

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(monkeypatch):
    """Remplace `psycopg.connect` et note ses arguments."""
    conn = _FakeConnection()

    def fake_connect(conninfo, **kwargs):
        conn.calls.append(kwargs)
        return conn

    monkeypatch.setattr(vector_store.psycopg, "connect", fake_connect)
    monkeypatch.setattr(vector_store, "register_vector", lambda c: None)
    return conn


def test_connection_is_bounded_in_time(connection):
    """Une base qui ne répond plus ne doit pas bloquer la tâche jusqu'à son délai de 6 h."""
    with vector_store.PgVectorStore("dbname=rag"):
        pass
    assert connection.calls[0]["connect_timeout"] == vector_store.CONNECT_TIMEOUT_S
    assert ("SELECT set_config('statement_timeout', %s, false)",
            (str(vector_store.STATEMENT_TIMEOUT_MS),)) in connection.executed


def test_connection_is_closed_when_register_vector_fails(connection, monkeypatch):
    """Un amorçage raté ne laisse pas de connexion ouverte (`__exit__` n'est pas appelé)."""
    def broken(conn):
        raise RuntimeError("extension vector absente")

    monkeypatch.setattr(vector_store, "register_vector", broken)
    with pytest.raises(RuntimeError, match="extension vector"), vector_store.PgVectorStore("dbname=rag"):
        pass
    assert connection.closed
