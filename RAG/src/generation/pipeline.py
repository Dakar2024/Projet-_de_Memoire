"""Pipeline d'une question (recherche puis génération) ; un emplacement par fil, jamais partagé (connexion psycopg)."""
from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg
import requests

from RAG.src.generation.answer import Answer, generate_answer
from RAG.src.retrieval.retriever import SearchResult, Searcher, build_llm_client
from RAG.src.utils.config import DEFAULT_CONFIG_PATH, load_generation_config, load_service_settings


def _quietly(close: Callable[[], object]) -> None:
    """Nettoie sur un chemin d'erreur en ignorant son propre échec (l'erreur d'origine prime)."""
    try:
        close()
    except Exception:  # noqa: BLE001 - l'erreur d'origine est relevée par l'appelant
        pass


@dataclass(frozen=True)
class PipelineResult:
    """Réponse, recherche et durées d'une question."""

    answer: Answer
    search: SearchResult
    timings_ms: dict[str, float]

    def as_dict(self, include_trace: bool) -> dict:
        """Construit le corps de réponse de l'API ; la trace seulement sur demande."""
        a = self.answer
        data = {"status": a.status, "answer": a.answer, "history": list(a.history),
                "sources": [s.as_dict() for s in a.sources], "disclaimer": a.disclaimer,
                "scope_reason": a.scope_reason, "timings_ms": dict(self.timings_ms)}
        if include_trace:
            data["trace"] = self.search.as_dict()["trace"]
            data["trace"]["generation"] = {"provider_name": a.provider_name, "model": a.model,
                                           "cost_usd": a.cost_usd, "rejected": a.rejected, "from_llm": a.from_llm}
        return data


def answer_question(question: str, *, search: Callable[[str], SearchResult],
                    generate: Callable[[str, SearchResult], Answer],
                    clock: Callable[[], float] = time.perf_counter) -> PipelineResult:
    """Enchaîne recherche et génération en les chronométrant."""
    start = clock()
    result = search(question)
    searched = clock()
    answer = generate(question, result)
    end = clock()
    analysis_ms = float(result.trace.timings_ms.get("analysis", 0.0))
    return PipelineResult(answer=answer, search=result, timings_ms={
        "analysis": analysis_ms, "search": (searched - start) * 1000,
        "generation": answer.latency_ms, "total": (end - start) * 1000})


@dataclass
class Slot:
    """Emplacement : un `Searcher` (une connexion PostgreSQL) et un client de génération."""

    searcher: Searcher
    generator: object


class QuestionPipeline:
    """Ouvre `slots` emplacements à l'entrée et les ferme à la sortie ; `acquire` ne bloque jamais."""

    def __init__(self, slots: int, *, config_path: Path = DEFAULT_CONFIG_PATH, env=None,
                 analysis_cache_path: Path | None = None) -> None:
        if analysis_cache_path is not None and slots > 1:
            raise ValueError("le cache d'analyse exige un seul emplacement")
        self._n = slots
        self._config_path, self._env, self._cache_path = config_path, env, analysis_cache_path
        self._generation = load_generation_config(config_path)
        self._free: queue.Queue[Slot] = queue.Queue()
        self._all: list[Slot] = []
        self._busy: set[int] = set()
        self._lock = threading.Lock()

    def __enter__(self) -> QuestionPipeline:
        """Ouvre tous les emplacements, ou referme ceux déjà ouverts en cas d'échec."""
        try:
            for _ in range(self._n):
                searcher = Searcher(config_path=self._config_path, env=self._env, cache_path=self._cache_path)
                try:
                    searcher.__enter__()
                except BaseException:
                    # Base non ouverte : fermer quand même les sessions HTTP.
                    _quietly(searcher.close)
                    raise
                try:
                    generator = build_llm_client(self._generation.profile, self._env, self._generation.timeout_s)
                except BaseException:
                    _quietly(lambda: searcher.__exit__(None, None, None))
                    raise
                slot = Slot(searcher, generator)
                self._all.append(slot)
                self._free.put(slot)
        except BaseException:
            _quietly(lambda: self.__exit__(None, None, None))
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        """Ferme tous les emplacements, même si l'un d'eux échoue ; relève la première erreur."""
        first: BaseException | None = None
        for slot in self._all:
            for close in (lambda: slot.searcher.__exit__(None, None, None), slot.generator.close):
                try:
                    close()
                except Exception as exc:  # noqa: BLE001 - on ferme tout avant de relever
                    first = first or exc
        self._all.clear()
        self._busy.clear()
        self._free = queue.Queue()
        if first is not None:
            raise first

    def acquire(self) -> Slot | None:
        """Prend un emplacement libre, ou None s'il n'y en a pas."""
        try:
            slot = self._free.get_nowait()
        except queue.Empty:
            return None
        with self._lock:
            self._busy.add(id(slot))
        return slot

    def release(self, slot: Slot) -> None:
        """Rend un emplacement acquis ; un double rendu lève (il ferait partager une connexion)."""
        with self._lock:
            if id(slot) not in self._busy:
                raise RuntimeError("emplacement non acquis ou déjà rendu")
            self._busy.remove(id(slot))
        self._free.put(slot)

    def ask(self, slot: Slot, question: str) -> PipelineResult:
        """Répond à une question avec l'emplacement fourni."""
        g = self._generation
        return answer_question(
            question, search=slot.searcher.search,
            generate=lambda q, r: generate_answer(q, r, client=slot.generator, profile=g.profile,
                                                  max_tokens=g.max_tokens))

    def ready(self) -> dict[str, bool]:
        """Indique si la base et le service d'embedding répondent (connexion courte, hors emplacement)."""
        services = load_service_settings(self._env)
        status = {"database": False, "embeddings": False}
        try:
            with psycopg.connect(services.pg_conninfo, connect_timeout=5) as conn:
                conn.execute("SELECT 1")
            status["database"] = True
        except psycopg.Error:
            pass
        try:
            status["embeddings"] = requests.get(f"{services.embeddings_url}/health", timeout=5).status_code == 200
        except requests.RequestException:
            pass
        return status
