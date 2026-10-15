"""Sérialisation des enregistrements en JSONL gzippé."""
from __future__ import annotations

import gzip
import json


def dumps_gzipped(records: list[dict]) -> bytes:
    """Sérialise des réponses d'API telles quelles en JSONL gzippé (contrat de la couche raw)."""
    body = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    )
    return gzip.compress(body.encode("utf-8"))
