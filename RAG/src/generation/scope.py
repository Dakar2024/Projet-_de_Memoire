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

# Contexte personnel (texte normalisé : sans accents). Les verbes ambigus « peut-il » et « indiqué »
# ne valent conseil clinique qu'avec lui : « Ce variant peut-il causer une anémie ? » est factuelle.
_PERSONAL = (
    r"(?=.*(?:\b(?:je|moi|mon|ma|mes|nous|notre|nos|vous|votre|vos|soeur|mere|fille|fils|frere|"
    r"pere|tante|oncle|cousines?|femme|mari|enfants?|famille|patiente?s?|porteu(?:r|se)s?)\b"
    r"|\b[jm]'|\bme\b))"
)

# Ordre d'examen : du plus spécifique au plus général. « Classe selon les critères ACMG »
# reste « acmg » même si la phrase contient aussi « nombre de ».
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("acmg", (
        r"\bacmg\b",
        r"\bamp\b",
        r"\b(?:pvs1|ps[1-4]|pm[1-6]|pp[1-5]|ba1|bs[1-4]|bp[1-7])\b",
        r"\bcriteres?\s+de\s+classification\b",
        r"\bamerican\s+college\s+of\s+medical\s+genetics\b",
        r"\bgrilles?\s+de\s+classification\b",
        # « Classe(r) le variant X selon les critères… » ; « classé selon ClinVar », « selon les
        # laboratoires » ou « selon les soumissionnaires » n'en sont pas (donnée ClinVar).
        r"\bclasse[rz]?\b(?:\s+\S+){0,8}?\s+selon\b"
        r"(?!\s+(?:clinvar|les\s+(?:laboratoires|soumissionnaires)\b))",
    )),
    ("frequency", (
        r"\bfrequences?\b",
        r"\bfrequente?s?\b",
        r"\bprevalences?\b",
        r"\bproportion\s+de\s+la\s+population\b",
        r"\bgnomad\b",
        r"\balleles?\b.*\bpopulations?\b",
        # « maladie rare » désigne une catégorie de maladies, « au courant » est une locution.
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
        # « indiquée(s) », « indiqués » ; « indiqué » masculin seulement après « est/sont » (sinon
        # « Qu'indique ClinVar » serait pris, les accents étant retirés).
        # Seulement avec un contexte personnel (« indiqué comme pathogène par ClinVar » est une donnée).
        r"^" + _PERSONAL + r".*\b(?:indiquees?|indiques)\b",
        r"^" + _PERSONAL + r".*\b(?:est|sont|serai(?:t|ent))(?:[- ](?:t[- ])?(?:il|elle|ils|elles))?\s+indique\b",
        r"\b[ms]'inquieter\b",
        r"\bavoir\s+des\s+enfants\b",
        r"\brisques?\b.*\bpour\s+(?:moi|elle|lui)\b",
        r"\bretirer\b.*\bovaires?\b",
        # « ablation de l'exon / du gène / du domaine / de la région » est un événement génétique.
        r"\bablations?\b(?!(?:\s+(?:de\s+l'|du|de\s+la|des))?\s*(?:exon|gene|domaine|region))",
    )),
    ("counting", (
        r"\bcombien\b",
        # « nombre de soumissionnaires » est une donnée de la fiche, pas un comptage.
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
