"""Contre le vrai rag-postgres (conteneur rag-api-test). Exclus de la passe rapide."""

import os

import psycopg
import pytest

pytestmark = pytest.mark.integration

READER = os.environ.get("RAG_TEST_PG_READER_CONNINFO")


@pytest.fixture
def reader():
    if not READER:
        pytest.skip("RAG_TEST_PG_READER_CONNINFO absent")
    with psycopg.connect(READER, autocommit=True) as conn:
        yield conn


def test_reader_cannot_create_a_temporary_table(reader):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("CREATE TEMP TABLE t (x int)")


def test_reader_cannot_write(reader):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("DELETE FROM rag_documents WHERE false")


def test_roles_have_no_administrative_attribute(reader):
    rows = reader.execute(
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolreplication "
        "FROM pg_roles WHERE rolname IN ('rag_indexer', 'rag_reader') ORDER BY rolname").fetchall()
    assert [r[0] for r in rows] == ["rag_indexer", "rag_reader"]
    assert all(not any(r[1:]) for r in rows)
