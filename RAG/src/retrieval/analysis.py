"""Analyse de la question par un LLM, avec validation stricte, cache et dégradation.

Le LLM n'est pas indispensable : s'il est indisponible, s'il est servi par le mauvais
fournisseur ou s'il répond hors schéma, la recherche continue avec la question brute
et sans filtre de signification, et la trace le dit. Seules les erreurs permanentes
(clé refusée, crédit épuisé) interrompent la recherche.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from RAG.src.prompts import analysis as prompts
from RAG.src.prompts.analysis import ANALYSIS_SCHEMA, SCHEMA_NAME, SYSTEM_PROMPT, user_message
from RAG.src.retrieval.significance import SIGNIFICANCE_VALUES
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import LlmProviderMismatchError, LlmUnavailableError, RagConfigurationError

_KEYS = {"english_query", "significance", "disease"}
_MAX_QUERY_CHARS = 2000
_MAX_DISEASE_CHARS = 300


@dataclass(frozen=True)
class QueryAnalysis:
    english_query: str
    significance: str
    disease: str | None
    available: bool
    profile: str
    provider_name: str | None = None
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    from_cache: bool = False
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def validate_analysis(content: Mapping) -> tuple[str, str, str | None]:
    """Revérifie ce que le schéma impose déjà : un point d'accès peut traiter le schéma
    comme une simple suggestion (documentation OpenRouter)."""
    if set(content) != _KEYS:
        raise ValueError(f"clés attendues {sorted(_KEYS)}, reçues {sorted(content)}")
    query, significance, disease = content["english_query"], content["significance"], content["disease"]
    if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_CHARS:
        raise ValueError("english_query vide, non textuelle ou trop longue")
    if significance not in SIGNIFICANCE_VALUES:
        raise ValueError(f"significance hors énumération : {significance!r}")
    if disease is not None and (not isinstance(disease, str) or len(disease) > _MAX_DISEASE_CHARS):
        raise ValueError("disease doit être un texte court ou null")
    return query.strip(), significance, (disease.strip() or None) if disease else None


class AnalysisCache:
    """Analyses réussies, sur disque. Clé : version et empreinte du prompt, modèle, point
    d'accès et texte exact de la question. Un rejeu redonne exactement la même analyse.

    Une entrée relue conserve le coût, la latence et le fournisseur de l'appel d'origine :
    la mesure compare le coût unitaire d'analyse par modèle, et une reprise doit donner le
    même total. `from_cache` distingue les rejeux. Un seul écrivain à la fois (mesure
    séquentielle). Le fichier est une entrée non fiable : illisible, il interrompt au lieu
    d'être réinitialisé en silence (cela refacturerait)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RagConfigurationError(f"cache d'analyse illisible : {path} ({exc})") from exc
            if not isinstance(data, dict):
                raise RagConfigurationError(f"cache d'analyse invalide (objet JSON attendu) : {path}")
            self._data = data

    @staticmethod
    def key(question: str, profile: LlmProfile) -> str:
        # Empreinte relue à chaque appel : elle suit le prompt réellement en vigueur.
        raw = "\0".join((prompts.PROMPT_VERSION, prompts.prompt_sha256(), profile.model,
                         profile.provider_tag, question))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, question: str, profile: LlmProfile) -> dict | None:
        return self._data.get(self.key(question, profile))

    def put(self, question: str, profile: LlmProfile, value: dict) -> None:
        self._data[self.key(question, profile)] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)


def _valid_entry(entry: object) -> bool:
    """Une entrée de cache éditée à la main ne doit jamais atteindre la recherche."""
    if not isinstance(entry, dict):
        return False
    try:
        validate_analysis({k: entry[k] for k in _KEYS})
    except (KeyError, ValueError, TypeError):
        return False
    numbers = (entry.get("cost_usd"), entry.get("latency_ms"))
    return (isinstance(entry.get("provider_name"), str)
            and all(isinstance(n, (int, float)) and not isinstance(n, bool) and n >= 0 for n in numbers))


def analyze(question: str, *, client, profile: LlmProfile, max_tokens: int,
            cache: AnalysisCache | None = None,
            clock: Callable[[], float] = time.perf_counter) -> QueryAnalysis:
    """Analyse la question. Limite connue : si le LLM est indisponible ou servi par le mauvais
    fournisseur, le coût reste 0,0 (l'exception ne porte pas l'appel) ; une réponse payée
    mais invalide conserve en revanche son coût et son fournisseur."""
    cached = cache.get(question, profile) if cache is not None else None
    if cached is not None and _valid_entry(cached):
        stored = {k: cached[k] for k in (*_KEYS, "provider_name", "cost_usd", "latency_ms")}
        return QueryAnalysis(available=True, profile=profile.name, from_cache=True, **stored)
    start = clock()
    try:
        call = client.complete_json(profile, system=SYSTEM_PROMPT, user=user_message(question),
                                    schema_name=SCHEMA_NAME, schema=ANALYSIS_SCHEMA, max_tokens=max_tokens)
    except (LlmUnavailableError, LlmProviderMismatchError) as exc:
        return QueryAnalysis(english_query=question, significance="none", disease=None, available=False,
                             profile=profile.name, latency_ms=(clock() - start) * 1000,
                             error=f"{type(exc).__name__}: {str(exc)[:200]}")
    try:
        query, significance, disease = validate_analysis(call.content)
    except ValueError as exc:
        return QueryAnalysis(english_query=question, significance="none", disease=None, available=False,
                             profile=profile.name, provider_name=call.provider_name,
                             cost_usd=call.cost_usd, latency_ms=(clock() - start) * 1000,
                             error=f"{type(exc).__name__}: {str(exc)[:200]}")
    stored = {"english_query": query, "significance": significance, "disease": disease,
              "provider_name": call.provider_name, "cost_usd": call.cost_usd,
              "latency_ms": (clock() - start) * 1000}
    if cache is not None:
        cache.put(question, profile, stored)
    return QueryAnalysis(available=True, profile=profile.name, **stored)
