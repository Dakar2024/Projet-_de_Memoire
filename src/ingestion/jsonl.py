"""Sérialisation des enregistrements en JSONL gzippé."""
from __future__ import annotations

import gzip
import json


def dumps_gzipped(records: list[dict]) -> bytes:
    """Sérialise des enregistrements en JSONL gzippé.

    JSONL parce que c'est le seul format qui préserve la réponse d'API mot pour mot
    tout en restant lisible ligne à ligne, sans imposer de schéma — donc sans
    transformation, ce qu'exige le contrat de la couche raw.
    """
    body = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    )
    return gzip.compress(body.encode("utf-8"))
