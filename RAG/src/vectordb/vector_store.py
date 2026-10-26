"""Accès à la base vectorielle (PostgreSQL + pgvector) : interface `VectorStore` et implémentation réelle."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, Self

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

# Délais de la connexion d'indexation : sans eux, seule l'échéance de 6 h de la tâche borne une base muette.
CONNECT_TIMEOUT_S = 10
# Le plus long ordre (DELETE d'un panel entier) prend quelques secondes : 5 min laisse une marge large.
STATEMENT_TIMEOUT_MS = 300_000

_ROW_FIELDS = (
    "doc_id", "chunk_id", "doc_type", "text", "gene_symbol", "clinical_significance",
    "review_status", "rs_dbsnp", "hgvs_c", "hgvs_p", "clinvar_variation_id", "clinvar_url",
    "source_version", "collected_at",
)


def _lock_key(panel: str) -> str:
    """Clé du verrou consultatif d'indexation d'un panel."""
    return f"rag_index:{panel}"


class VectorStore(Protocol):
    """Interface de la base vectorielle dont dépend l'indexation."""

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
    """Connexion unique pour toute l'indexation (le verrou appartient à la session), une transaction par écriture."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._conn: psycopg.Connection | None = None

    def __enter__(self) -> Self:
        conn = psycopg.connect(self._conninfo, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S)
        try:
            conn.execute("SELECT set_config('statement_timeout', %s, false)", (str(STATEMENT_TIMEOUT_MS),))
            register_vector(conn)
        except BaseException:
            # `__exit__` n'est pas appelé si `__enter__` échoue : sans ceci la connexion fuit.
            conn.close()
            raise
        self._conn = conn
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
        """Prend le verrou du panel sans attendre ; renvoie False s'il est déjà pris."""
        row = self._db.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (_lock_key(panel),)).fetchone()
        return bool(row[0])

    def unlock(self, panel: str) -> None:
        """Libère le verrou du panel."""
        self._db.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_lock_key(panel),))

    def indexed_state(self, panel: str) -> dict[str, tuple[str, str]]:
        """Renvoie, par `doc_id` indexé, son `chunk_id` et son modèle d'embedding."""
        rows = self._db.execute(
            "SELECT doc_id, chunk_id, embedding_model FROM rag_documents WHERE panel = %s", (panel,)
        ).fetchall()
        return {doc_id: (chunk, model) for doc_id, chunk, model in rows}

    def delete(self, panel: str, doc_ids: Sequence[str]) -> None:
        """Supprime des documents du panel en une transaction."""
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
        """Insère ou met à jour un lot de documents et leurs vecteurs en une transaction."""
        if vectors.shape != (len(rows), EMBEDDING_DIM):
            raise ValueError(f"{len(rows)} lignes pour des vecteurs de forme {vectors.shape}")
        # float32 numpy : psycopg refuse une liste Python pour une colonne `vector`.
        params = [
            {**{field: row[field] for field in _ROW_FIELDS}, "panel": panel,
             "embedding": vector.astype(np.float32), "embedding_model": embedding_model}
            for row, vector in zip(rows, vectors, strict=True)
        ]
        with self._db.transaction(), self._db.cursor() as cursor:
            cursor.executemany(_UPSERT, params)
