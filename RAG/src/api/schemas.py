"""Schémas de l'API : question de 1 à 1 000 caractères, tout champ inconnu refusé."""
from __future__ import annotations

from typing import Annotated

import msgspec


class QuestionIn(msgspec.Struct, forbid_unknown_fields=True):
    """Corps de POST /v1/questions."""
    question: Annotated[str, msgspec.Meta(min_length=1, max_length=1000)]
    trace: bool = False
