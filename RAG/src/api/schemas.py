"""Schémas de l'API. La question est bornée ici (1–1 000 caractères) ; tout champ
inconnu est refusé."""

from __future__ import annotations

from typing import Annotated

import msgspec


class QuestionIn(msgspec.Struct, forbid_unknown_fields=True):
    question: Annotated[str, msgspec.Meta(min_length=1, max_length=1000)]
    trace: bool = False
