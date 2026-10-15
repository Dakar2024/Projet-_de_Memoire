"""Faux service d'embedding et fausse base, qui respectent les interfaces réelles,
pour tester l'algorithme d'indexation sans conteneur."""

from __future__ import annotations

import hashlib

import numpy as np


def vector_for(text: str) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    v = np.random.default_rng(seed).normal(size=768).astype(np.float32)
    return v / np.linalg.norm(v)


class FakeEmbeddingClient:
    def __init__(self, max_tokens: int = 512):
        self.max_tokens = max_tokens
        self.embedded: list[str] = []

    def max_input_length(self) -> int:
        return self.max_tokens

    def token_counts(self, texts):
        return [len(text.split()) + 2 for text in texts]

    def embed(self, texts):
        self.embedded.extend(texts)
        return np.stack([vector_for(text) for text in texts])


class InMemoryStore:
    def __init__(self, fail_after_upserts: int | None = None):
        self.rows: dict[tuple[str, str], dict] = {}
        self.locked: set[str] = set()
        self.upserts = 0
        self.writes = 0
        self._fail_after = fail_after_upserts

    def try_lock(self, panel):
        if panel in self.locked:
            return False
        self.locked.add(panel)
        return True

    def unlock(self, panel):
        self.locked.discard(panel)

    def indexed_state(self, panel):
        return {doc: (row["chunk_id"], row["embedding_model"])
                for (p, doc), row in self.rows.items() if p == panel}

    def delete(self, panel, doc_ids):
        if doc_ids:
            self.writes += 1
        for doc_id in doc_ids:
            self.rows.pop((panel, doc_id), None)

    def upsert(self, panel, rows, vectors, embedding_model):
        if self._fail_after is not None and self.upserts >= self._fail_after:
            raise ConnectionError("interruption simulée")
        self.upserts += 1
        self.writes += 1
        for row, vector in zip(rows, vectors, strict=True):
            self.rows[(panel, row["doc_id"])] = {**row, "embedding": vector, "embedding_model": embedding_model}
