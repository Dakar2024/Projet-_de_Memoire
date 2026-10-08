"""Contrôles déterministes de la réponse générée, en plus du prompt : citations parmi
les documents transmis, identifiants (rs, HGVS, ClinVar, gènes) présents dans ces documents,
significations conformes aux documents cités. Un échec lève GenerationRejectedError
avec un code court ; la réponse est alors remplacée par un message fixe.

Règle de l'historique de classification : le LLM ne le raconte pas, le code le restitue
(tâche 5) à partir de la ligne Gold « Classification history ». La réponse ne peut donc
citer que la signification ACTUELLE des documents cités. Raison : trois tours de motifs
(« auparavant », « jusqu'en <date> », « précédemment »…) ont montré qu'un historique raconté
en langue libre n'est pas contrôlable de façon sûre, chaque assouplissement rouvrant un
contournement (« Comme indiqué précédemment, il est de signification incertaine »)."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Sequence

from RAG.src.generation.messages import SIGNIFICANCE_FR, significance_terms_fr, translate_significance
from RAG.src.retrieval.identifiers import extract_identifiers
from RAG.src.retrieval.retriever import RetrievedDocument
from RAG.src.utils.errors import GenerationRejectedError

# Identifiant ClinVar : « Variation ID », « ClinVar ID/n°/# », « VCV », « /variation/ ». Un nombre
# nu après « ClinVar » n'en est pas un s'il ressemble à une année, une date ou un effectif.
_VARIATION_ID = re.compile(
    r"(?:Variation(?:\s+ID)?|ClinVar(?:\s+(?:ID|n°|no\.?|#)|(?!\s*[:#°]?\s*(?:19|20)\d\d\b))|VCV0*|/variation/)"
    r"\s*[:#°]?\s*(\d{2,9})\b(?!-\d)(?!\s*(?:soumett|laborat|submitter|centre))",
    re.IGNORECASE,
)
_LABELS = sorted(SIGNIFICANCE_FR, key=len, reverse=True)
_TYPOGRAPHY = str.maketrans({c: " " for c in "«»’‘“”…\u00a0\u202f"})
# Tirets Unicode (U+2010 à U+2015, signe moins U+2212) ramenés à « - » : « c.68‑2A>G »
# écrit avec un trait d'union insécable reste un HGVS intronique contrôlé.
_DASHES = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})
_PANEL_STATUSES = ("answered", "partial")


def _clean(answer: str) -> str:
    """Réponse remise sous forme comparable : entités HTML décodées (c.69A&gt;G), Unicode
    normalisé (NFKC : pleine chasse, ligatures) et caractères de format (Cf : largeur nulle,
    trait d'union conditionnel, liant de mots) retirés, car ils casseraient « rs12345 » ;
    tirets Unicode ramenés à « - »."""
    text = unicodedata.normalize("NFKC", html.unescape(answer))
    return "".join(c for c in text if unicodedata.category(c) != "Cf").translate(_DASHES)


def check_citations(citations: Sequence[str], documents: Sequence[RetrievedDocument], status: str) -> None:
    transmitted = {d.doc_id for d in documents}
    if any(c not in transmitted for c in citations):
        raise GenerationRejectedError("citation_not_transmitted")
    if status in ("answered", "partial") and not citations:
        raise GenerationRejectedError("no_citation")


def _identifiers_of(texts: Sequence[str]) -> tuple[set, set, set]:
    rs, c, p = set(), set(), set()
    for text in texts:
        ids = extract_identifiers(text)
        rs |= set(ids.rs)
        c |= set(ids.hgvs_c)
        p |= set(ids.hgvs_p)
    return rs, c, p


def check_identifiers(answer: str, documents: Sequence[RetrievedDocument], status: str = "answered") -> None:
    """Tout identifiant de la réponse (rs, HGVS, ClinVar, gène) figure dans les documents
    transmis. La typographie française (guillemets, apostrophe, espaces insécables) est
    ramenée à des espaces avant extraction : elle ne doit pas cacher un identifiant inventé."""
    answer = _clean(answer).translate(_TYPOGRAPHY)
    allowed_rs, allowed_c, allowed_p = _identifiers_of([d.text for d in documents])
    allowed_rs |= {d.rs_dbsnp for d in documents if d.rs_dbsnp is not None}
    allowed_c |= {d.hgvs_c for d in documents if d.hgvs_c}
    allowed_p |= {d.hgvs_p for d in documents if d.hgvs_p}
    allowed_vid = {d.clinvar_variation_id for d in documents if d.clinvar_variation_id}
    for d in documents:
        allowed_vid |= set(_VARIATION_ID.findall(d.text))
    found = extract_identifiers(answer)
    if (set(found.rs) - allowed_rs or set(found.hgvs_c) - allowed_c or set(found.hgvs_p) - allowed_p
            or set(_VARIATION_ID.findall(answer)) - allowed_vid):
        raise GenerationRejectedError("identifier_not_in_sources")
    if status in _PANEL_STATUSES:
        # Symboles autorisés : ceux que les textes transmis contiennent (« group D1 », RAD51,
        # CD4 recopiés fidèlement) et les gènes des documents.
        allowed_genes = {d.gene_symbol for d in documents if d.gene_symbol}
        for d in documents:
            ids = extract_identifiers(d.text)
            allowed_genes |= set(ids.genes) | set(ids.out_of_panel)
        if (set(found.genes) | set(found.out_of_panel)) - allowed_genes:
            raise GenerationRejectedError("identifier_not_in_sources")


def _spaced(text: str) -> str:
    """Motif d'une expression : les espaces deviennent \\s+ (plusieurs espaces tolérés)."""
    return r"\s+".join(re.escape(word) for word in text.split())


def _french_pattern(term: str) -> str:
    for key, pattern in _FEMININE_PLURAL.items():
        if term.endswith(key):
            prefix = term[: -len(key)].strip()
            lead = _spaced(prefix) + r"\s+" if prefix else ""
            return rf"\b{lead}(?:{pattern})\b"
    return rf"\b{_spaced(term)}\b"


_FEMININE_PLURAL = {"bénin": r"b[ée]nin(?:e|s|es)?|b[ée]nigne(?:s)?",
                    "pathogène": r"pathog[èe]ne(?:s)?",
                    "signification incertaine": r"signification(?:s)?\s+(?:\S+\s+){0,2}?incertaine(?:s)?",
                    "interprétations contradictoires":
                        r"interpr[ée]tation(?:s)?\s+(?:\S+\s+){0,3}?contradictoire(?:s)?"}


def _build_terms() -> list[tuple[str, re.Pattern]]:
    """Termes de signification reconnus dans une réponse : (clé française, motif), en
    français et avec le libellé ClinVar anglais, du plus long au plus court pour que
    « probablement pathogène » masque le « pathogène » qu'il contient."""
    entries: list[tuple[int, str, str]] = []
    for term in significance_terms_fr():
        entries.append((len(term), term, _french_pattern(term)))
    for label, fr in SIGNIFICANCE_FR.items():
        if label in ("other", "not provided"):
            continue
        entries.append((len(label), fr, rf"\b{_spaced(label)}\b"))
    entries.append((len("facteur de risque"), "facteur de risque", r"\bfacteurs?\s+de\s+risque\b"))
    entries.append((len("faible pénétrance"), "faible pénétrance", r"\bfaible\s+p[ée]n[ée]trance\b"))
    entries.sort(key=lambda e: e[0], reverse=True)
    return [(fr, re.compile(pat, re.IGNORECASE)) for _, fr, pat in entries]


_TERMS = _build_terms()
# Qualificatifs hors table : rejetés d'office, qu'ils figurent ou non dans les documents.
_OFF_TABLE = re.compile(
    r"\bVUS\b|\bd[ée]l[ée]t[èe]res?\b|\bneutres?\b|\bind[ée]termin[ée]e?s?\b|"
    r"\bsignification\s+inconnue\b|\bpathog[ée]niques?\b|\bvraisemblablement\b|\bà\s+risque\b",
    re.IGNORECASE,
)
_NEGATIONS = {"pas", "non", "ni", "jamais", "plus", "aucun", "aucune"}
_SENTENCES = re.compile(r"(?<=[.!?;])\s+")


def _negated(text: str, start: int) -> bool:
    words = re.findall(r"[\wéèêàçùô']+", text[:start].lower())[-3:]
    return any(word in _NEGATIONS for word in words)


def _terms_in(sentence: str) -> set[str]:
    """Termes de signification d'une phrase, sans double compte. Une négation dans les trois
    mots qui précèdent un terme rend la phrase invérifiable (conservateur)."""
    found: set[str] = set()
    remaining = sentence
    for term, pattern in _TERMS:
        for match in pattern.finditer(remaining):
            if _negated(sentence, match.start()):
                raise GenerationRejectedError("significance_not_in_sources")
            found.add(term)
        remaining = pattern.sub(lambda m: " " * len(m.group()), remaining)
    # « incertaine » isolé dans une phrase qui parle de « signification » vaut « signification
    # incertaine » (« Sa signification clinique est encore incertaine »).
    if "signification incertaine" not in found and re.search(r"\bsignification", sentence, re.IGNORECASE):
        lone = re.search(r"\bincertain(?:e|s|es)?\b", sentence, re.IGNORECASE)
        if lone:
            if _negated(sentence, lone.start()):
                raise GenerationRejectedError("significance_not_in_sources")
            found.add("signification incertaine")
    return found


def _labels_in(text: str) -> set[str]:
    found, remaining = set(), text
    for label in _LABELS:
        pattern = re.compile(rf"\b{re.escape(label)}\b")
        if pattern.search(remaining):
            found.add(label)
            remaining = pattern.sub(" ", remaining)
    return found


# Ligne de la signification actuelle ; elle s'arrête avant une éventuelle ligne d'historique.
_CURRENT_LINE = re.compile(r"Clinical significance:\s*(.*?)(?:\.(?:\s|$)|\n|Classification history:|$)")


def _translated(labels: set[str]) -> set[str]:
    """Traduction française des libellés ClinVar, composites découpés (« Pathogenic/Likely
    pathogenic »)."""
    out: set[str] = set()
    for label in labels:
        for part in re.split(r"/|; |, ", label):
            translated = translate_significance(part.strip())
            if translated:
                out.add(translated)
    return out


def check_significances(answer: str, cited: Sequence[RetrievedDocument]) -> None:
    """Chaque signification de la réponse est la signification actuelle d'un document cité
    (champ `clinical_significance` et ligne « Clinical significance »). Un libellé de la ligne
    « Classification history » est rejeté : l'historique est restitué par le code. Limite
    connue : deux documents cités peuvent permuter leurs significations sans être détectés."""
    current: set[str] = set()
    for d in cited:
        labels = {d.clinical_significance} if d.clinical_significance else set()
        for match in _CURRENT_LINE.finditer(d.text):
            labels |= _labels_in(match.group(1))
        current |= _translated(labels)
    text = _clean(answer)
    if _OFF_TABLE.search(text):
        raise GenerationRejectedError("significance_not_in_sources")
    for sentence in _SENTENCES.split(text):
        if _terms_in(sentence) - current:
            raise GenerationRejectedError("significance_not_in_sources")
