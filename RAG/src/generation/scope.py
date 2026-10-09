"""Hors périmètre détecté par règles, avant tout appel au LLM (E2b).

Constat de la recette : le prompt seul ne suffit pas (« Combien de variants pathogènes
compte BRCA2 ? » a reçu « Le gène BRCA2 compte 1 variant pathogène »). Ces règles
déterministes tranchent d'abord ; la règle du prompt reste un second filet.

Règles écrites avec la série de développement (`questions_recette_e2b.yaml`) et des
phrases inventées, jamais avec la série de contrôle, réservée à la mesure. Elles vont dans
le sens prudent : une question détectée à tort reçoit un message fixe, jamais une réponse
fausse. Les faux positifs sont vérifiés sur les 89 questions de `questions_recherche.yaml`.
"""

from __future__ import annotations

import re
import unicodedata

# Ordre d'examen : du plus spécifique au plus général. « Classe selon les critères ACMG »
# reste « acmg » même si la phrase contient aussi « nombre de ».
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("acmg", (
        r"\bacmg\b",
        r"\bamp\b",
        r"\b(?:pvs1|ps[1-4]|pm[1-6]|pp[1-5]|ba1|bs[1-4]|bp[1-7])\b",
        r"\bcriteres?\s+de\s+classification\b",
        # « Classe(r) le variant X selon les critères… » ; « classé selon ClinVar » n'en est pas.
        r"\bclasse[rz]?\b(?:\s+\S+){0,8}?\s+selon\b(?!\s+clinvar)",
    )),
    ("frequency", (
        r"\bfrequences?\b",
        r"\bfrequente?s?\b",
        r"\bprevalences?\b",
        r"\bproportion\s+de\s+la\s+population\b",
        r"\bgnomad\b",
        r"\balleles?\b.*\bpopulations?\b",
    )),
    ("clinical_advice", (
        r"\bfaut[- ]il\b",
        r"\bdoit[- ]on\b",
        r"\btraitements?\b",
        r"\btraiter\b",
        r"\bprescri\w*",
        r"\bmedicaments?\b",
        r"\bprise\s+en\s+charge\b",
        r"\bsuivi\b",
        r"\brecommand\w*",
        r"\bmastectomies?\b",
        r"\bchirurgi\w*",
        r"\bdepistages?\b",
    )),
    ("counting", (
        r"\bcombien\b",
        r"\bnombre\s+(?:de|d')",
        r"\blistes?\s+(?:complete|exhaustive)s?\b",
        r"\btous\s+les\s+variants?\b",
        r"\btoutes\s+les\s+variantes?\b",
        r"\benumer\w*",
        r"\ble\s+plus\s+de\b",
        r"\ble\s+moins\s+de\b",
        r"\ble\s+plus\s+grand\s+nombre\b",
        r"\bquel(?:le)?s?\s+genes?\b.*\ble\s+plus\b",
    )),
)
_COMPILED = tuple((reason, tuple(re.compile(p) for p in patterns)) for reason, patterns in _RULES)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})


def normalize(question: str) -> str:
    """Minuscules, Unicode NFKC, accents retirés (une question tapée sans accent est
    reconnue de même), apostrophes typographiques ramenées à « ' », espaces réduits."""
    text = unicodedata.normalize("NFKC", question).translate(_APOSTROPHES).lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def detect_out_of_scope(question: str) -> str | None:
    """Raison hors périmètre (counting, acmg, frequency, clinical_advice) ou `None`."""
    text = normalize(question)
    for reason, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            return reason
    return None
