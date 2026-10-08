"""Contrôles déterministes de la réponse générée, en plus du prompt : citations parmi
les documents transmis, identifiants (rs, HGVS, ClinVar) présents dans ces documents,
significations conformes aux documents cités. Un échec lève GenerationRejectedError
avec un code court ; la réponse est alors remplacée par un message fixe."""

from __future__ import annotations

import re
from collections.abc import Sequence

from RAG.src.generation.messages import SIGNIFICANCE_FR, significance_terms_fr, translate_significance
from RAG.src.retrieval.identifiers import extract_identifiers
from RAG.src.retrieval.retriever import RetrievedDocument
from RAG.src.utils.errors import GenerationRejectedError

_VARIATION_ID = re.compile(r"(?:Variation ID|ClinVar|VCV0*)\s*:?\s*(\d{2,9})\b", re.IGNORECASE)
_LABELS = sorted(SIGNIFICANCE_FR, key=len, reverse=True)
_FEMININE_PLURAL = {"bénin": r"b[ée]nin(?:e|s|es)?|b[ée]nigne(?:s)?",
                    "pathogène": r"pathog[èe]ne(?:s)?",
                    "signification incertaine": r"signification(?:s)? incertaine(?:s)?",
                    "interprétations contradictoires": r"interpr[ée]tation(?:s)? contradictoire(?:s)?"}


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


def check_identifiers(answer: str, documents: Sequence[RetrievedDocument]) -> None:
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


def _term_pattern(term: str) -> re.Pattern:
    for key, pattern in _FEMININE_PLURAL.items():
        if term.endswith(key):
            prefix = term[: -len(key)]
            return re.compile(rf"\b{re.escape(prefix)}(?:{pattern})\b", re.IGNORECASE)
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


_TERMS = [(term, _term_pattern(term)) for term in significance_terms_fr()]


def _terms_in(text: str) -> set[str]:
    """Termes de signification d'un texte français, sans double compte : « probablement
    pathogène » masque le « pathogène » qu'il contient."""
    found, remaining = set(), text
    for term, pattern in _TERMS:
        if pattern.search(remaining):
            found.add(term)
            remaining = pattern.sub(" ", remaining)
    return found


def _labels_in(text: str) -> set[str]:
    found, remaining = set(), text
    for label in _LABELS:
        pattern = re.compile(rf"\b{re.escape(label)}\b")
        if pattern.search(remaining):
            found.add(label)
            remaining = pattern.sub(" ", remaining)
    return found


def check_significances(answer: str, cited: Sequence[RetrievedDocument]) -> None:
    allowed: set[str] = set()
    for d in cited:
        for label in _labels_in(d.text) | ({d.clinical_significance} if d.clinical_significance else set()):
            for part in re.split(r"/|; |, ", label):
                translated = translate_significance(part.strip())
                if translated:
                    allowed.add(translated)
    if _terms_in(answer) - allowed:
        raise GenerationRejectedError("significance_not_in_sources")
