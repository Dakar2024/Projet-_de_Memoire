"""Contre le vrai rag-postgres (conteneur rag-api-test). Exclus de la passe rapide."""

import os

import psycopg
import psycopg.conninfo
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


INDEXER = os.environ.get("RAG_TEST_PG_CONNINFO")
TEST_PANEL = "__test_durcissement__"


@pytest.fixture
def indexer():
    if not INDEXER:
        pytest.skip("RAG_TEST_PG_CONNINFO absent")
    with psycopg.connect(INDEXER) as conn:
        yield conn
        conn.rollback()


def test_indexer_keeps_its_write_rights_after_hardening(indexer):
    """Les droits de l'indexeur, exercés pour de vrai, dans une transaction annulée."""
    vector = "[" + ",".join(["0"] * 767 + ["1"]) + "]"
    with indexer.transaction(force_rollback=True):
        indexer.execute(
            "INSERT INTO rag_documents (panel, doc_id, chunk_id, doc_type, text, embedding, embedding_model) "
            "VALUES (%s, 'd1', 'c1', 'variant', 't', %s::vector, 'm')", (TEST_PANEL, vector))
        indexer.execute("UPDATE rag_documents SET text = 'u' WHERE panel = %s", (TEST_PANEL,))
        assert indexer.execute("SELECT text FROM rag_documents WHERE panel = %s", (TEST_PANEL,)).fetchone() == ("u",)
        assert indexer.execute("DELETE FROM rag_documents WHERE panel = %s", (TEST_PANEL,)).rowcount == 1


@pytest.mark.parametrize("sql", ["CREATE TABLE t (x int)", "CREATE TEMP TABLE t (x int)",
                                 "ALTER TABLE rag_documents ADD COLUMN x int"])
def test_indexer_cannot_change_the_schema(indexer, sql):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        indexer.execute(sql)


@pytest.mark.parametrize("which", ["reader", "indexer"])
@pytest.mark.parametrize("database", ["postgres", "template1"])
def test_application_roles_cannot_connect_to_administrative_databases(which, database):
    conninfo = READER if which == "reader" else INDEXER
    if not conninfo:
        pytest.skip("chaîne de connexion de test absente")
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        psycopg.connect(psycopg.conninfo.make_conninfo(conninfo, dbname=database), connect_timeout=10).close()
