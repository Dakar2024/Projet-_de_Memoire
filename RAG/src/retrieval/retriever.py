"""Recherche hybride (E2a) : exact → filtres → similarité, avec garde-fous.

Toutes les étapes utilisent la recherche vectorielle exacte (l'index HNSW perd la moitié
des documents pertinents sur ce corpus, cf. PgSearchStore) ; `force_exact=False` ne sert
qu'à la mesure de diagnostic de l'index.

`search()` ne connaît aucun service : l'analyse, la vectorisation et la base lui sont
passées, ce qui la rend testable sans réseau. `Searcher` fait le câblage réel et
vérifie d'abord, comme l'indexation, que le service d'embedding sert le modèle de
l'index (empreinte, puis canari).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from ingestion.config import PANEL_GENES
from RAG.src.embeddings.canary import load_canary, verify_canary
from RAG.src.embeddings.embedder import EmbeddingClient
from RAG.src.llm.groq import GroqClient
from RAG.src.llm.openrouter import OpenRouterClient
from RAG.src.retrieval.analysis import AnalysisCache, QueryAnalysis, analyze
from RAG.src.retrieval.identifiers import Identifiers, extract_identifiers
from RAG.src.retrieval.significance import clinvar_labels
from RAG.src.utils.config import (
    DEFAULT_CONFIG_PATH,
    LlmProfile,
    SearchConfig,
    check_served_model,
    load_config,
    load_groq_key,
    load_openrouter_key,
    load_search_config,
    load_service_settings,
    served_fingerprint,
)
from RAG.src.utils.errors import QuestionRejectedError, RagConfigurationError

MODES = ("similarity", "filters", "full")
PANELS = tuple(PANEL_GENES)
_COLUMNS = ("doc_id", "doc_type", "text", "gene_symbol", "clinical_significance", "rs_dbsnp",
            "hgvs_c", "hgvs_p", "clinvar_url", "source_version")


@dataclass(frozen=True)
class RetrievedDocument:
    doc_id: str
    doc_type: str
    text: str
    gene_symbol: str | None
    clinical_significance: str | None
    rs_dbsnp: int | None
    hgvs_c: str | None
    hgvs_p: str | None
    clinvar_url: str | None
    source_version: str | None
    similarity: float
    stage: str


@dataclass
class SearchTrace:
    mode: str
    identifiers: Identifiers
    analysis: QueryAnalysis
    genes_filter: tuple[str, ...] = ()
    significance_labels: tuple[str, ...] = ()
    exact_search: bool = False
    flags: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    question: str
    documents: tuple[RetrievedDocument, ...]
    trace: SearchTrace

    def as_dict(self) -> dict:
        trace = asdict(self.trace)
        trace["identifiers"] = self.trace.identifiers.as_dict()
        trace["analysis"] = self.trace.analysis.as_dict()
        return {"question": self.question, "documents": [asdict(d) for d in self.documents], "trace": trace}


@dataclass(frozen=True)
class SearchSettings:
    k: int
    min_filtered: int
    max_question_chars: int


class SearchStore(Protocol):
    def known_significances(self) -> tuple[str, ...]: ...
    def exact_matches(self, *, rs: Sequence[int], hgvs_c: Sequence[str], hgvs_p: Sequence[str],
                      genes: Sequence[str], query_vector: np.ndarray, limit: int) -> list[RetrievedDocument]: ...
    def similar(self, *, query_vector: np.ndarray, genes: Sequence[str], significances: Sequence[str],
                exclude_doc_ids: Sequence[str], limit: int, exact: bool) -> list[RetrievedDocument]: ...


def validate_question(question: str, max_chars: int) -> str:
    text = (question or "").strip()
    if not text:
        raise QuestionRejectedError("question vide")
    if len(text) > max_chars:
        raise QuestionRejectedError(f"question de {len(text)} caractères, plafond {max_chars}")
    return text


def search(question: str, *, settings: SearchSettings, analyze: Callable[[str], QueryAnalysis],
           embed: Callable[[str], np.ndarray], store: SearchStore, mode: str = "full",
           force_exact: bool | None = None, clock: Callable[[], float] = time.perf_counter) -> SearchResult:
    if mode not in MODES:
        raise ValueError(f"mode inconnu : {mode!r}")
    text = validate_question(question, settings.max_question_chars)
    ids = extract_identifiers(text)
    timings: dict[str, float] = {}

    start = clock()
    result_analysis = analyze(text)
    timings["analysis"] = (clock() - start) * 1000
    start = clock()
    vector = embed(result_analysis.english_query)
    timings["embedding"] = (clock() - start) * 1000

    trace = SearchTrace(mode=mode, identifiers=ids, analysis=result_analysis, timings_ms=timings)
    if ids.out_of_panel:
        trace.flags.append("gene_out_of_panel")
    if not result_analysis.available:
        trace.flags.append("analysis_unavailable")

    use_filters = mode in ("filters", "full")
    genes = ids.genes if use_filters else ()
    labels = clinvar_labels(result_analysis.significance, store.known_significances()) if use_filters else ()

    start = clock()
    documents: list[RetrievedDocument] = []
    if mode == "full" and ids.has_variant_identifier:
        # Une position HGVS est relative à un gène : sans gène du panneau cité (seulement un gène
        # hors panneau), elle correspondrait à d'autres gènes. On ne cherche alors que le `rs`.
        hgvs_searchable = not (ids.out_of_panel and not ids.genes)
        hgvs_c, hgvs_p = (ids.hgvs_c, ids.hgvs_p) if hgvs_searchable else ((), ())
        if ids.rs or hgvs_c or hgvs_p:
            documents = store.exact_matches(rs=ids.rs, hgvs_c=hgvs_c, hgvs_p=hgvs_p, genes=ids.genes,
                                            query_vector=vector, limit=settings.k)
        if not documents:
            trace.flags.append("identifier_not_found")

    remaining = settings.k - len(documents)
    if remaining > 0:
        # Toujours exacte par défaut : l'index HNSW ne retrouve que la moitié des documents
        # pertinents (voir PgSearchStore). `force_exact=False` ne sert qu'au diagnostic.
        exact = force_exact if force_exact is not None else True
        found = store.similar(query_vector=vector, genes=genes, significances=labels,
                              exclude_doc_ids=[d.doc_id for d in documents], limit=remaining, exact=exact)
        if labels and len(found) < min(settings.min_filtered, remaining):
            trace.flags.append("significance_relaxed")
            labels = ()
            exact = force_exact if force_exact is not None else True
            found = store.similar(query_vector=vector, genes=genes, significances=(),
                                  exclude_doc_ids=[d.doc_id for d in documents], limit=remaining, exact=exact)
        trace.exact_search = exact
        documents += found
    timings["database"] = (clock() - start) * 1000

    trace.genes_filter, trace.significance_labels = tuple(genes), tuple(labels)
    return SearchResult(question=text, documents=tuple(documents), trace=trace)


def _resorted(sql: str) -> str:
    """`relaxed_order` peut rendre des lignes légèrement désordonnées : on retrie le
    résultat (colonne `similarity`, en dernier, donc `_documents` reste valable). Les
    égalités sont départagées par `doc_id` : une mesure rejouée garde le même ordre."""
    return f"WITH r AS MATERIALIZED ({sql}) SELECT * FROM r ORDER BY similarity DESC, doc_id"


def _inner_order(exact: bool) -> str:
    """Tri de la requête interne. En recherche exacte, `doc_id` départage les égalités
    de distance (sinon le choix des `limit` premiers dépend du plan). En recherche
    approchée, un second critère empêcherait PostgreSQL d'utiliser l'index HNSW : les
    égalités à la frontière de `limit` y restent non déterministes (limite connue)."""
    return "ORDER BY embedding <=> %(q)s, doc_id" if exact else "ORDER BY embedding <=> %(q)s"


def doc_ids_sha256(doc_ids: Iterable[str]) -> str:
    """Empreinte d'un ensemble de documents : `doc_id` triés en Python (pas par la base ni
    par Polars, dont l'ordre des chaînes pourrait différer), joints par des retours à la
    ligne. Calculée de la même façon sur le Gold (vérité terrain) et sur l'index (mesure)."""
    return hashlib.sha256("\n".join(sorted(doc_ids)).encode("utf-8")).hexdigest()


def check_index_models(models: Sequence[str], expected: str) -> None:
    """L'index doit avoir été construit par un seul modèle : celui que sert le service."""
    if tuple(models) != (expected,):
        raise RagConfigurationError(
            f"modèles présents dans l'index : {list(models)} ; empreinte attendue : {expected}. "
            "Réindexer ou corriger la configuration avant toute recherche.")


class PgSearchStore:
    """Lecture seule (`rag_reader`). Délais bornés : connexion 10 s, requête 30 s.
    La recherche est toujours exacte (balayage séquentiel). Mesuré le 05/10/2026 sur
    l'index réel (59 questions) : le rappel@10 de l'index HNSW face à la recherche
    exacte est de 0,47 à ef_search 40, 0,58 à 200, 0,66 à 400 et 1,00 seulement à 1000
    (808 ms, pas plus rapide que l'exacte, 714 ms) ; le parcours itératif n'y change
    rien. Cause probable, non vérifiée : 32 % des documents ont un corps identique, donc
    des vecteurs identiques. L'index HNSW reste en place, inutilisé (`exact=False`
    réservé au diagnostic) ; à réévaluer si le corpus grandit."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._conn: psycopg.Connection | None = None
        self._known: tuple[str, ...] | None = None

    def __enter__(self) -> PgSearchStore:
        # prepare_threshold=None : psycopg prépare sinon une requête après 5 exécutions, et
        # PostgreSQL peut alors réutiliser un plan générique bâti sous un autre réglage
        # `enable_indexscan` ; une recherche filtrée « exacte » redeviendrait silencieusement
        # un parcours HNSW filtré après coup.
        conn = psycopg.connect(self._conninfo, autocommit=True, connect_timeout=10, prepare_threshold=None)
        try:
            register_vector(conn)
        except Exception:
            conn.close()
            raise
        self._conn = conn
        return self

    def __exit__(self, *exc_info) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> psycopg.Connection:
        if self._conn is None:
            raise RuntimeError("PgSearchStore s'utilise dans un bloc `with`")
        return self._conn

    def _rows(self, sql: str, params: dict, *, exact: bool, limit: int) -> list[tuple]:
        with self._db.transaction():
            self._db.execute("SELECT set_config('statement_timeout', '30s', true)")
            if exact:
                self._db.execute("SELECT set_config('enable_indexscan', 'off', true)")
            else:
                self._db.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
                self._db.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(max(40, 4 * limit)),))
            return self._db.execute(sql, params).fetchall()

    def _timed(self, sql: str, params: tuple) -> list[tuple]:
        """Requête simple de lecture, avec le même délai de 30 s que les recherches."""
        with self._db.transaction():
            self._db.execute("SELECT set_config('statement_timeout', '30s', true)")
            return self._db.execute(sql, params).fetchall()

    @staticmethod
    def _documents(rows: list[tuple], stage: str) -> list[RetrievedDocument]:
        return [RetrievedDocument(**dict(zip(_COLUMNS, row[:-1], strict=True)), similarity=float(row[-1]),
                                  stage=stage) for row in rows]

    def known_significances(self) -> tuple[str, ...]:
        if self._known is None:
            rows = self._timed(
                "SELECT DISTINCT clinical_significance FROM rag_documents "
                "WHERE clinical_significance IS NOT NULL AND panel = ANY(%s::text[])", (list(PANELS),)
            )
            self._known = tuple(sorted(row[0] for row in rows))
        return self._known

    def index_models(self) -> tuple[str, ...]:
        rows = self._timed("SELECT DISTINCT embedding_model FROM rag_documents "
                           "WHERE panel = ANY(%s::text[])", (list(PANELS),))
        return tuple(sorted(row[0] for row in rows))

    def doc_ids_sha256(self) -> str:
        """Empreinte des documents indexés pour les panels mesurés (panel de test exclu)."""
        rows = self._timed("SELECT doc_id FROM rag_documents WHERE panel = ANY(%s::text[])", (list(PANELS),))
        return doc_ids_sha256(row[0] for row in rows)

    def exact_matches(self, *, rs, hgvs_c, hgvs_p, genes, query_vector, limit):
        sql = f"""
            SELECT {', '.join(_COLUMNS)}, 1 - (embedding <=> %(q)s) AS similarity
            FROM rag_documents
            WHERE panel = ANY(%(panels)s::text[]) AND doc_type = 'variant'
              AND (rs_dbsnp = ANY(%(rs)s::bigint[]) OR hgvs_c = ANY(%(c)s::text[]) OR hgvs_p = ANY(%(p)s::text[]))
              AND (cardinality(%(genes)s::text[]) = 0 OR gene_symbol = ANY(%(genes)s::text[]))
            {_inner_order(True)} LIMIT %(limit)s"""
        params = {"q": query_vector.astype(np.float32), "panels": list(PANELS), "rs": list(rs),
                  "c": list(hgvs_c), "p": list(hgvs_p), "genes": list(genes), "limit": limit}
        return self._documents(self._rows(_resorted(sql), params, exact=True, limit=limit), "exact")

    def similar(self, *, query_vector, genes, significances, exclude_doc_ids, limit, exact):
        sql = f"""
            SELECT {', '.join(_COLUMNS)}, 1 - (embedding <=> %(q)s) AS similarity
            FROM rag_documents
            WHERE panel = ANY(%(panels)s::text[])
              AND (cardinality(%(genes)s::text[]) = 0 OR gene_symbol = ANY(%(genes)s::text[]))
              AND (cardinality(%(sig)s::text[]) = 0 OR clinical_significance = ANY(%(sig)s::text[]))
              AND NOT (doc_id = ANY(%(exclude)s::text[]))
            {_inner_order(exact)} LIMIT %(limit)s"""
        params = {"q": query_vector.astype(np.float32), "panels": list(PANELS), "genes": list(genes),
                  "sig": list(significances), "exclude": list(exclude_doc_ids), "limit": limit}
        stage = "filtered" if (genes or significances) else "similarity"
        return self._documents(self._rows(_resorted(sql), params, exact=exact, limit=limit), stage)


def build_llm_client(profile: LlmProfile, env, timeout_s: float) -> OpenRouterClient | GroqClient:
    """Client du profil : OpenRouter (mesure officielle) ou Groq (essai gratuit). Seule la
    clé du client choisi est exigée."""
    if profile.backend == "openrouter":
        return OpenRouterClient(load_openrouter_key(env), timeout_s=timeout_s)
    if profile.backend == "groq":
        return GroqClient(load_groq_key(env), timeout_s=timeout_s)
    raise RagConfigurationError(f"profil {profile.name} : backend {profile.backend!r} inconnu")


class Searcher:
    """Câblage réel, ouvert une fois : vérifie le modèle d'embedding, puis assemble le
    client LLM du profil, le service d'embedding et la base (`rag_reader`)."""

    def __init__(self, *, profile_name: str | None = None, cache_path: Path | None = None,
                 config_path: Path = DEFAULT_CONFIG_PATH, env=None) -> None:
        rag = load_config(config_path)
        self.config: SearchConfig = load_search_config(config_path, profile_name)
        services = load_service_settings(env)
        check_served_model(rag.embedding.fingerprint, served_fingerprint(services.served_model_dir))
        self._embedder = EmbeddingClient(services.embeddings_url, services.embeddings_api_key,
                                         timeout_s=rag.embedding.request_timeout_s)
        self._fingerprint = rag.embedding.fingerprint
        verify_canary(self._embedder, load_canary(rag.embedding.canary_path), rag.embedding.fingerprint,
                      rag.embedding.canary_min_cosine)
        self._llm = build_llm_client(self.config.analysis_profile, env, self.config.llm_timeout_s)
        self._cache = AnalysisCache(cache_path) if cache_path else None
        self._store = PgSearchStore(services.pg_conninfo)
        self._settings = SearchSettings(self.config.k, self.config.min_filtered, self.config.max_question_chars)

    def __enter__(self) -> Searcher:
        self._store.__enter__()
        try:
            check_index_models(self._store.index_models(), self._fingerprint)
        except BaseException:
            self._store.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        self._store.__exit__(*exc_info)

    def index_doc_ids_sha256(self) -> str:
        """Empreinte des documents de l'index, à comparer à celle de la vérité terrain."""
        return self._store.doc_ids_sha256()

    def search(self, question: str, mode: str = "full", force_exact: bool | None = None) -> SearchResult:
        profile = self.config.analysis_profile
        return search(
            question, settings=self._settings, store=self._store, mode=mode, force_exact=force_exact,
            analyze=lambda q: analyze(q, client=self._llm, profile=profile,
                                      max_tokens=self.config.llm_max_tokens, cache=self._cache),
            embed=lambda text: self._embedder.embed([text])[0],
        )
