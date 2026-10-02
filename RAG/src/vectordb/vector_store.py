"""Accès à la base vectorielle (PostgreSQL + pgvector).

`VectorStore` est l'interface dont dépend l'indexation ; `PgVectorStore` en est
l'implémentation réelle. La passe rapide des tests utilise une fausse base qui
respecte la même interface (RAG/tests/fakes.py).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from RAG.src.embeddings.embedder import EMBEDDING_DIM

_UPSERT = """
INSERT INTO rag_documents (
    panel, doc_id, chunk_id, doc_type, text, gene_symbol, clinical_significance,
    review_status, rs_dbsnp, hgvs_c, hgvs_p, clinvar_variation_id, clinvar_url,
    source_version, collected_at, embedding, embedding_model, indexed_at
) VALUES (
    %(panel)s, %(doc_id)s, %(chunk_id)s, %(doc_type)s, %(text)s, %(gene_symbol)s,
    %(clinical_significance)s, %(review_status)s, %(rs_dbsnp)s, %(hgvs_c)s, %(hgvs_p)s,
    %(clinvar_variation_id)s, %(clinvar_url)s, %(source_version)s, %(collected_at)s,
    %(embedding)s, %(embedding_model)s, now()
)
ON CONFLICT (panel, doc_id) DO UPDATE SET
    chunk_id = EXCLUDED.chunk_id, doc_type = EXCLUDED.doc_type, text = EXCLUDED.text,
    gene_symbol = EXCLUDED.gene_symbol, clinical_significance = EXCLUDED.clinical_significance,
    review_status = EXCLUDED.review_status, rs_dbsnp = EXCLUDED.rs_dbsnp,
    hgvs_c = EXCLUDED.hgvs_c, hgvs_p = EXCLUDED.hgvs_p,
    clinvar_variation_id = EXCLUDED.clinvar_variation_id, clinvar_url = EXCLUDED.clinvar_url,
    source_version = EXCLUDED.source_version, collected_at = EXCLUDED.collected_at,
    embedding = EXCLUDED.embedding, embedding_model = EXCLUDED.embedding_model,
    indexed_at = now()
"""

_ROW_FIELDS = (
    "doc_id", "chunk_id", "doc_type", "text", "gene_symbol", "clinical_significance",
    "review_status", "rs_dbsnp", "hgvs_c", "hgvs_p", "clinvar_variation_id", "clinvar_url",
    "source_version", "collected_at",
)


def _lock_key(panel: str) -> str:
    return f"rag_index:{panel}"


class VectorStore(Protocol):
    def try_lock(self, panel: str) -> bool: ...
    def unlock(self, panel: str) -> None: ...
    def indexed_state(self, panel: str) -> dict[str, tuple[str, str]]: ...
    def delete(self, panel: str, doc_ids: Sequence[str]) -> None: ...
    def upsert(
        self,
        panel: str,
        rows: Sequence[Mapping[str, object]],
        vectors: np.ndarray,
        embedding_model: str,
    ) -> None: ...


class PgVectorStore:
    """Une connexion unique, en autocommit, gardée pendant toute l'indexation : le
    verrou consultatif PostgreSQL appartient à la session qui l'a pris. Chaque écriture
    est une transaction explicite, validée entière ou annulée entière."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._conn: psycopg.Connection | None = None

    def __enter__(self) -> PgVectorStore:
        self._conn = psycopg.connect(self._conninfo, autocommit=True)
        register_vector(self._conn)
        return self

    def __exit__(self, *exc_info) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> psycopg.Connection:
        if self._conn is None:
            raise RuntimeError("PgVectorStore s'utilise dans un bloc `with`")
        return self._conn

    def try_lock(self, panel: str) -> bool:
        row = self._db.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (_lock_key(panel),)).fetchone()
        return bool(row[0])

    def unlock(self, panel: str) -> None:
        self._db.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_lock_key(panel),))

    def indexed_state(self, panel: str) -> dict[str, tuple[str, str]]:
        rows = self._db.execute(
            "SELECT doc_id, chunk_id, embedding_model FROM rag_documents WHERE panel = %s", (panel,)
        ).fetchall()
        return {doc_id: (chunk, model) for doc_id, chunk, model in rows}

    def delete(self, panel: str, doc_ids: Sequence[str]) -> None:
        if not doc_ids:
            return
        with self._db.transaction():
            self._db.execute(
                "DELETE FROM rag_documents WHERE panel = %s AND doc_id = ANY(%s)", (panel, list(doc_ids))
            )

    def upsert(
        self,
        panel: str,
        rows: Sequence[Mapping[str, object]],
        vectors: np.ndarray,
        embedding_model: str,
    ) -> None:
        if vectors.shape != (len(rows), EMBEDDING_DIM):
            raise ValueError(f"{len(rows)} lignes pour des vecteurs de forme {vectors.shape}")
        # Les vecteurs passent en numpy float32 : psycopg refuse une liste Python
        # pour une colonne `vector` (vérifié le 02/10/2026).
        params = [
            {**{field: row[field] for field in _ROW_FIELDS}, "panel": panel,
             "embedding": vector.astype(np.float32), "embedding_model": embedding_model}
            for row, vector in zip(rows, vectors, strict=True)
        ]
        with self._db.transaction(), self._db.cursor() as cursor:
            cursor.executemany(_UPSERT, params)
