"""Génération de la réponse : LLM, revalidation, contrôles déterministes ; sources et historique viennent de la base."""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

from RAG.src.generation import messages
from RAG.src.generation.checks import strip_cited_labels, verify_answer
from RAG.src.generation.context import build_context, resolve_citations
from RAG.src.generation.scope import detect_out_of_scope
from RAG.src.prompts.generation import (
    GENERATION_SCHEMA, GENERATION_SCHEMA_NAME, MAX_ANSWER_CHARS, SCOPE_REASONS, STATUSES, SYSTEM_PROMPT,
    user_message,
)
from RAG.src.retrieval.retriever import RetrievedDocument, SearchResult
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import GenerationRejectedError, LlmTruncatedError, LlmUnavailableError

_KEYS = {"status", "scope_reason", "answer", "citations"}
# Ligne écrite par silver_to_gold_rag : « Classification history: previously X until D. »
_HISTORY_LINE = re.compile(r"Classification history: previously (?P<label>.+?) until (?P<until>[^.\n]+)\.")


@dataclass(frozen=True)
class Source:
    """Métadonnées d'une source citée, lues en base."""

    doc_id: str
    gene: str | None
    variant: str | None
    protein: str | None
    significance: str | None
    significance_fr: str | None
    review_status: str | None
    clinvar_variation_id: str | None
    clinvar_url: str | None
    archive: str | None
    previous_significance: str | None = None
    previous_significance_fr: str | None = None
    previous_until: str | None = None

    def as_dict(self) -> dict:
        """Sérialise la source."""
        return asdict(self)


@dataclass(frozen=True)
class Answer:
    """Réponse livrée, avec ses sources, son avertissement et le coût de génération."""

    status: str
    answer: str
    sources: tuple[Source, ...]
    disclaimer: str
    scope_reason: str | None
    rejected: str | None
    provider_name: str | None
    model: str | None
    cost_usd: float
    latency_ms: float
    from_llm: bool
    history: tuple[str, ...] = ()
    # Texte libre d'un `not_in_sources` : jamais livré, seule la recette le consigne.
    llm_text_withheld: str | None = None

    def as_dict(self) -> dict:
        """Sérialise la réponse, sans le texte retenu."""
        data = asdict(self)
        data.pop("llm_text_withheld")
        data["sources"] = [s.as_dict() for s in self.sources]
        data["history"] = list(self.history)
        return data


def _source(d: RetrievedDocument) -> Source:
    """Construit une source à partir d'un document, historique compris."""
    match = _HISTORY_LINE.search(d.text)
    previous = match.group("label").strip() if match else None
    return Source(doc_id=d.doc_id, gene=d.gene_symbol, variant=d.hgvs_c, protein=d.hgvs_p,
                  significance=d.clinical_significance,
                  significance_fr=messages.translate_significance(d.clinical_significance),
                  review_status=d.review_status, clinvar_variation_id=d.clinvar_variation_id,
                  clinvar_url=d.clinvar_url, archive=d.source_version,
                  previous_significance=previous,
                  previous_significance_fr=messages.translate_significance(previous),
                  previous_until=match.group("until").strip() if match else None)


def _history(sources) -> tuple[str, ...]:
    """Rend une phrase d'historique par source citée qui en a un, dans l'ordre des citations."""
    return tuple(messages.history_sentence(s.variant or s.protein, s.clinvar_variation_id,
                                           s.previous_significance_fr, s.previous_until)
                 for s in sources if s.previous_significance_fr and s.previous_until)


def _archive(documents) -> str | None:
    """Renvoie l'archive ClinVar la plus récente des documents."""
    versions = sorted({d.source_version for d in documents if d.source_version})
    return versions[-1] if versions else None


def validate_generation(content: Mapping) -> tuple[str, str | None, str, list[str]]:
    """Revalide la sortie du LLM contre le schéma, sans faire confiance au fournisseur."""
    if not isinstance(content, Mapping) or set(content) != _KEYS:
        raise ValueError("clés inattendues")
    status, reason, text, citations = content["status"], content["scope_reason"], content["answer"], content["citations"]
    if status not in STATUSES:
        raise ValueError("status hors énumération")
    if status == "out_of_scope":
        if reason not in SCOPE_REASONS:
            raise ValueError("scope_reason requis pour out_of_scope")
    elif reason is not None:
        raise ValueError("scope_reason doit être null hors out_of_scope")
    if not isinstance(text, str) or len(text) > MAX_ANSWER_CHARS:
        raise ValueError("answer non textuelle ou trop longue")
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        raise ValueError("citations doit être une liste de textes")
    # « \\n » littéral parfois émis par le modèle, ramené à un vrai retour à la ligne.
    return status, reason, text.replace("\\n", "\n").strip(), list(dict.fromkeys(citations))


def _fixed(status: str, text: str, documents, *, reason: str | None = None, sources=()) -> Answer:
    """Construit une réponse à message fixe, sans appel au LLM."""
    return Answer(status=status, answer=text, sources=tuple(sources), disclaimer=messages.disclaimer(_archive(documents)),
                  scope_reason=reason, rejected=None, provider_name=None, model=None, cost_usd=0.0,
                  latency_ms=0.0, from_llm=False)


def generate_answer(question: str, result: SearchResult, *, client, profile: LlmProfile, max_tokens: int,
                    clock: Callable[[], float] = time.perf_counter) -> Answer:
    """Répond à la question : messages fixes si possible, sinon LLM puis contrôles déterministes."""
    documents, trace = list(result.documents), result.trace
    ids = trace.identifiers
    # Cas tranchés sans LLM : gène hors panel seul, identifiants tous absents, hors périmètre, aucun document.
    if "gene_out_of_panel" in trace.flags and not ids.genes and not ids.has_variant_identifier:
        return _fixed("out_of_scope", messages.OUT_OF_SCOPE["gene_out_of_panel"], documents, reason="gene_out_of_panel")
    cited_ids = [f"rs{r}" for r in ids.rs] + list(ids.hgvs_c) + list(ids.hgvs_p)
    if cited_ids and set(cited_ids) <= set(trace.not_found_identifiers):
        return _fixed("not_in_sources", messages.identifiers_not_found(cited_ids), documents)
    scope = detect_out_of_scope(question)
    if scope is not None:
        return _fixed("out_of_scope", messages.OUT_OF_SCOPE[scope], documents, reason=scope)
    if not documents:
        return _fixed("not_in_sources", messages.NO_DOCUMENT, documents)

    start = clock()
    try:
        call = client.complete_json(profile, system=SYSTEM_PROMPT,
                                    user=user_message(question, build_context(documents), list(trace.flags)),
                                    schema_name=GENERATION_SCHEMA_NAME, schema=GENERATION_SCHEMA,
                                    max_tokens=max_tokens)
    except LlmTruncatedError as exc:
        # Réponse coupée : traitée comme indisponible (503), pas comme une erreur interne.
        raise LlmUnavailableError("génération coupée ou vide") from exc
    latency = (clock() - start) * 1000
    try:
        status, reason, text, citations = validate_generation(call.content)
    except ValueError as exc:
        raise LlmUnavailableError(f"réponse de génération hors schéma : {exc}") from exc

    meta = dict(provider_name=call.provider_name, model=profile.model, cost_usd=call.cost_usd,
                latency_ms=latency, from_llm=True, disclaimer=messages.disclaimer(_archive(documents)))
    if status == "out_of_scope":
        return Answer(status=status, answer=messages.OUT_OF_SCOPE[reason], sources=(), scope_reason=reason,
                      rejected=None, **meta)
    if status == "not_in_sources":
        # Message fixe livré ; le texte du LLM n'est contrôlé que pour consigner un éventuel rejet.
        rejected = None
        try:
            verify_answer(text, [], [], status, question)
        except GenerationRejectedError as exc:
            rejected = str(exc)
        return Answer(status=status, answer=messages.NO_DOCUMENT, sources=(), scope_reason=None,
                      rejected=rejected, llm_text_withheld=text, **meta)
    # Étiquettes déjà citées retirées du texte ; toute autre étiquette reste rejetée.
    text = strip_cited_labels(text, citations)
    resolved = resolve_citations(citations, documents)
    try:
        verify_answer(text, documents, resolved, status, question)
    except GenerationRejectedError as exc:
        return Answer(status="unverifiable", answer=messages.UNVERIFIABLE,
                      sources=tuple(_source(d) for d in documents), scope_reason=None, rejected=str(exc), **meta)
    by_id = {d.doc_id: d for d in documents}
    sources = tuple(_source(by_id[c]) for c in dict.fromkeys(resolved))
    return Answer(status=status, answer=text, sources=sources, scope_reason=None, rejected=None,
                  history=_history(sources), **meta)
