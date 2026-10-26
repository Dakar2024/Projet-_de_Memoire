"""Détection du hors-périmètre par règles, avant le LLM (le prompt seul ne suffisait pas) ; sens prudent."""
from __future__ import annotations

import re
import unicodedata

# Contexte personnel : « peut-il » et « indiqué » ne valent conseil clinique qu'avec lui.
_PERSONAL = (
    r"(?=.*(?:\b(?:je|moi|mon|ma|mes|nous|notre|nos|vous|votre|vos|soeur|mere|fille|fils|frere|"
    r"pere|tante|oncle|cousines?|femme|mari|enfants?|famille|patiente?s?|porteu(?:r|se)s?)\b"
    r"|\b[jm]'|\bme\b))"
)

# Examinées du plus spécifique au plus général.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("acmg", (
        r"\bacmg\b",
        r"\bamp\b",
        r"\b(?:pvs1|ps[1-4]|pm[1-6]|pp[1-5]|ba1|bs[1-4]|bp[1-7])\b",
        r"\bcriteres?\s+de\s+classification\b",
        r"\bamerican\s+college\s+of\s+medical\s+genetics\b",
        r"\bgrilles?\s+de\s+classification\b",
        # « Classer … selon », sauf « selon ClinVar / les laboratoires / les soumissionnaires ».
        (r"\bclasse[rz]?\b(?:\s+\S+){0,8}?\s+selon\b"
        r"(?!\s+(?:clinvar|les\s+(?:laboratoires|soumissionnaires)\b))"),
    )),
    ("frequency", (
        r"\bfrequences?\b",
        r"\bfrequente?s?\b",
        r"\bprevalences?\b",
        r"\bproportion\s+de\s+la\s+population\b",
        r"\bgnomad\b",
        r"\balleles?\b.*\bpopulations?\b",
        # Sauf « maladie rare » et la locution « au courant ».
        r"(?<!maladie )(?<!maladies )\brares?\b",
        r"(?<!\bau )\bcourante?s?\b",
        r"\brepandue?s?\b",
        r"\bpourcentages?\b",
        r"\bmaf\b",
        r"\bincidences?\b",
        r"\bcombien\s+de\s+porteu\w+",
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
        r"\bdois[- ]je\b",
        r"\bdevrais[- ]je\b",
        r"\bdevrai(?:t|ent)[- ](?:il|elle|ils|elles)\b",
        r"\bpuis[- ]je\b",
        r"^" + _PERSONAL + r".*\bpeu(?:t|vent)[- ](?:il|elle|ils|elles)\b",
        r"\bconsulter\b",
        # « indiqué(e)(s) » avec contexte personnel seulement (« Qu'indique ClinVar » est une donnée).
        r"^" + _PERSONAL + r".*\b(?:indiquees?|indiques)\b",
        r"^" + _PERSONAL + r".*\b(?:est|sont|serai(?:t|ent))(?:[- ](?:t[- ])?(?:il|elle|ils|elles))?\s+indique\b",
        r"\b[ms]'inquieter\b",
        r"\bavoir\s+des\s+enfants\b",
        r"\brisques?\b.*\bpour\s+(?:moi|elle|lui)\b",
        r"\bretirer\b.*\bovaires?\b",
        # Sauf « ablation de l'exon / du gène / du domaine / de la région » (événement génétique).
        r"\bablations?\b(?!(?:\s+(?:de\s+l'|du|de\s+la|des))?\s*(?:exon|gene|domaine|region))",
    )),
    ("counting", (
        r"\bcombien\b",
        # Sauf « nombre de soumissionnaires », donnée de la fiche.
        r"\bnombre\s+(?:de|d')(?!\s*soumissionnaires?\b)",
        r"\blistes?\s+(?:complete|exhaustive)s?\b",
        r"\btous\s+les\s+variants?\b",
        r"\btoutes\s+les\s+variantes?\b",
        r"\benumer\w*",
        r"\bdecomptes?\b",
        r"\bl'ensemble\s+des\s+(?:variants|mutations|variantes)\b",
        r"\binventaires?\b",
        r"\bliste[sz]?\s+les\b",
        r"\bcite[sz]?\s+tou(?:te)?s\b",
        r"\bquelle\s+quantite\b",
        r"\ble\s+plus\s+de\b",
        r"\ble\s+moins\s+de\b",
        r"\ble\s+plus\s+grand\s+nombre\b",
        r"\bquel(?:le)?s?\s+genes?\b.*\ble\s+plus\b",
    )),
    # Listes fermées (création, culture générale) : le vocabulaire médical est ouvert, le reste va au LLM.
    ("other", (
        (r"\b(?:ecri[st]|ecrire|redige[sz]?|rediger|compose[sz]?|composer|invente[sz]?|inventer"
        r"|raconte[sz]?|raconter)\b.*\b(?:poemes?|chansons?|blagues?|histoires?|contes?|recits?"
        r"|haikus?|slogans?|romans?|nouvelles?|raps?|vers|dissertations?)\b"),
        r"\b(?:poemes?|chansons?|blagues?|haikus?|horoscopes?)\b",
        r"\bcapitales?\b",
        r"\bpresident(?:e|s|es)?\b",
        r"\bpremier\s+ministre\b",
        r"\bmeteo\b",
        r"\bfootball\b",
        r"\brecettes?\s+de\s+cuisine\b",
    )),
)
_COMPILED = tuple((reason, tuple(re.compile(p) for p in patterns)) for reason, patterns in _RULES)
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})


def normalize(question: str) -> str:
    """Normalise une question : minuscules, NFKC, sans accents, apostrophes droites, espaces réduits."""
    text = unicodedata.normalize("NFKC", question).translate(_APOSTROPHES).lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def detect_out_of_scope(question: str) -> str | None:
    """Renvoie la raison hors périmètre (counting, acmg, frequency, clinical_advice, other), ou None."""
    text = normalize(question)
    for reason, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            return reason
    return None
