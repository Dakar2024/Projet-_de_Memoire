"""Recherche hybride exact → filtres → similarité ; `search()` est pure, `Searcher` câble les services réels."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, Self

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
from RAG.src.utils.errors import IndexEmptyError, QuestionRejectedError, RagConfigurationError

MODES = ("similarity", "filters", "full")
PANELS = tuple(PANEL_GENES)
_COLUMNS = ("doc_id", "doc_type", "text", "gene_symbol", "clinical_significance",
            "review_status", "rs_dbsnp", "hgvs_c", "hgvs_p", "clinvar_variation_id", "clinvar_url",
            "source_version")


@dataclass(frozen=True)
class RetrievedDocument:
    """Document retrouvé, avec sa similarité et l'étape qui l'a trouvé."""

    doc_id: str
    doc_type: str
    text: str
    gene_symbol: str | None
    clinical_significance: str | None
    review_status: str | None
    rs_dbsnp: int | None
    hgvs_c: str | None
    hgvs_p: str | None
    clinvar_variation_id: str | None
    clinvar_url: str | None
    source_version: str | None
    similarity: float
    stage: str


@dataclass
class SearchTrace:
    """Trace d'une recherche : identifiants, analyse, filtres, signaux et durées."""

    mode: str
    identifiers: Identifiers
    analysis: QueryAnalysis
    genes_filter: tuple[str, ...] = ()
    significance_labels: tuple[str, ...] = ()
    exact_search: bool = False
    flags: list[str] = field(default_factory=list)
    not_found_identifiers: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    """Documents retrouvés et trace d'une recherche."""

    question: str
    documents: tuple[RetrievedDocument, ...]
    trace: SearchTrace

    def as_dict(self) -> dict:
        """Sérialise le résultat."""
        trace = asdict(self.trace)
        trace["identifiers"] = self.trace.identifiers.as_dict()
        trace["analysis"] = self.trace.analysis.as_dict()
        return {"question": self.question, "documents": [asdict(d) for d in self.documents], "trace": trace}


@dataclass(frozen=True)
class SearchSettings:
    """Réglages de la recherche."""

    k: int
    min_filtered: int
    max_question_chars: int


class SearchStore(Protocol):
    """Interface de lecture de la base dont dépend `search()`."""

    def known_significances(self) -> tuple[str, ...]: ...
    def exact_matches(self, *, rs: Sequence[int], hgvs_c: Sequence[str], hgvs_p: Sequence[str],
                      genes: Sequence[str], query_vector: np.ndarray, limit: int) -> list[RetrievedDocument]: ...
    def similar(self, *, query_vector: np.ndarray, genes: Sequence[str], significances: Sequence[str],
                exclude_doc_ids: Sequence[str], limit: int, exact: bool) -> list[RetrievedDocument]: ...


def validate_question(question: str, max_chars: int) -> str:
    """Refuse une question vide ou trop longue ; renvoie le texte nettoyé."""
    text = (question or "").strip()
    if not text:
        raise QuestionRejectedError("question vide")
    if len(text) > max_chars:
        raise QuestionRejectedError(f"question de {len(text)} caractères, plafond {max_chars}")
    return text


def _missing_identifiers(ids: Identifiers, searched_hgvs: bool, found: list[RetrievedDocument]) -> list[str]:
    """Renvoie les identifiants cités sans document exact (un HGVS non cherché compte comme introuvable)."""
    rs_found = {d.rs_dbsnp for d in found}
    c_found = {d.hgvs_c for d in found}
    p_found = {d.hgvs_p for d in found}
    missing = [f"rs{rs}" for rs in ids.rs if rs not in rs_found]
    missing += [c for c in ids.hgvs_c if not searched_hgvs or c not in c_found]
    missing += [p for p in ids.hgvs_p if not searched_hgvs or p not in p_found]
    return missing


def search(question: str, *, settings: SearchSettings, analyze: Callable[[str], QueryAnalysis],
           embed: Callable[[str], np.ndarray], store: SearchStore, mode: str = "full",
           force_exact: bool | None = None, clock: Callable[[], float] = time.perf_counter) -> SearchResult:
    """Cherche les documents d'une question : correspondance exacte, puis similarité filtrée, assouplie si besoin."""
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
        # HGVS relatif à un gène : avec un seul gène hors panel cité, seul le `rs` est cherché.
        hgvs_searchable = not (ids.out_of_panel and not ids.genes)
        hgvs_c, hgvs_p = (ids.hgvs_c, ids.hgvs_p) if hgvs_searchable else ((), ())
        if ids.rs or hgvs_c or hgvs_p:
            documents = store.exact_matches(rs=ids.rs, hgvs_c=hgvs_c, hgvs_p=hgvs_p, genes=ids.genes,
                                            query_vector=vector, limit=settings.k)
        trace.not_found_identifiers = _missing_identifiers(ids, hgvs_searchable, documents)
        if trace.not_found_identifiers:
            trace.flags.append("identifier_not_found")

    remaining = settings.k - len(documents)
    if remaining > 0:
        # Exacte par défaut (rappel HNSW 0,47) ; `force_exact=False` ne sert qu'au diagnostic.
        exact = force_exact if force_exact is not None else True
        found = store.similar(query_vector=vector, genes=genes, significances=labels,
                              exclude_doc_ids=[d.doc_id for d in documents], limit=remaining, exact=exact)
        if labels and len(found) < min(settings.min_filtered, remaining):
            trace.flags.append("significance_relaxed")
            labels = ()
            found = store.similar(query_vector=vector, genes=genes, significances=(),
                                  exclude_doc_ids=[d.doc_id for d in documents], limit=remaining, exact=exact)
        trace.exact_search = exact
        documents += found
    timings["database"] = (clock() - start) * 1000

    trace.genes_filter, trace.significance_labels = tuple(genes), tuple(labels)
    return SearchResult(question=text, documents=tuple(documents), trace=trace)


def _resorted(sql: str) -> str:
    """Retrie le résultat par similarité puis `doc_id`, pour un ordre stable d'un rejeu à l'autre."""
    return f"WITH r AS MATERIALIZED ({sql}) SELECT * FROM r ORDER BY similarity DESC, doc_id"


def _inner_order(exact: bool) -> str:
    """Renvoie le tri interne ; `doc_id` départage en exact (en approché, il empêcherait l'usage de HNSW)."""
    return "ORDER BY embedding <=> %(q)s, doc_id" if exact else "ORDER BY embedding <=> %(q)s"


def doc_ids_sha256(doc_ids: Iterable[str]) -> str:
    """Calcule l'empreinte d'un ensemble de `doc_id`, triés en Python, identique sur le Gold et sur l'index."""
    return hashlib.sha256("\n".join(sorted(doc_ids)).encode("utf-8")).hexdigest()


def check_index_models(models: Sequence[str], expected: str) -> bool:
    """Vérifie que l'index a été construit par le seul modèle servi ; False s'il est encore vide."""
    if not models:
        return False
    if tuple(models) != (expected,):
        raise RagConfigurationError(
            f"modèles présents dans l'index : {list(models)} ; empreinte attendue : {expected}. "
            "Réindexer ou corriger la configuration avant toute recherche.")
    return True


class PgSearchStore:
    """Base en lecture seule (`rag_reader`), délais bornés ; recherche exacte car le rappel HNSW mesuré n'est que de 0,47."""

    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._conn: psycopg.Connection | None = None
        self._known: tuple[str, ...] | None = None

    def __enter__(self) -> Self:
        # Pas de requête préparée : un plan générique pourrait réutiliser HNSW malgré `enable_indexscan`.
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
        """Exécute une recherche vectorielle exacte ou approchée, avec délai borné."""
        with self._db.transaction():
            self._db.execute("SELECT set_config('statement_timeout', '30s', true)")
            if exact:
                self._db.execute("SELECT set_config('enable_indexscan', 'off', true)")
            else:
                self._db.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
                self._db.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(max(40, 4 * limit)),))
            return self._db.execute(sql, params).fetchall()

    def ping(self) -> None:
        """Vérifie que la base répond."""
        self._timed("SELECT 1", ())

    def _timed(self, sql: str, params: tuple) -> list[tuple]:
        """Exécute une lecture simple avec le délai de 30 s."""
        with self._db.transaction():
            self._db.execute("SELECT set_config('statement_timeout', '30s', true)")
            return self._db.execute(sql, params).fetchall()

    @staticmethod
    def _documents(rows: list[tuple], stage: str) -> list[RetrievedDocument]:
        """Convertit les lignes en documents retrouvés."""
        return [RetrievedDocument(**dict(zip(_COLUMNS, row[:-1], strict=True)), similarity=float(row[-1]),
                                  stage=stage) for row in rows]

    def known_significances(self) -> tuple[str, ...]:
        """Renvoie les libellés de signification présents dans l'index (mis en cache)."""
        if self._known is None:
            rows = self._timed(
                "SELECT DISTINCT clinical_significance FROM rag_documents "
                "WHERE clinical_significance IS NOT NULL AND panel = ANY(%s::text[])", (list(PANELS),)
            )
            self._known = tuple(sorted(row[0] for row in rows))
        return self._known

    def index_models(self) -> tuple[str, ...]:
        """Renvoie les modèles d'embedding présents dans l'index."""
        rows = self._timed("SELECT DISTINCT embedding_model FROM rag_documents "
                           "WHERE panel = ANY(%s::text[])", (list(PANELS),))
        return tuple(sorted(row[0] for row in rows))

    def doc_ids_sha256(self) -> str:
        """Calcule l'empreinte des documents indexés des panels (panel de test exclu)."""
        rows = self._timed("SELECT doc_id FROM rag_documents WHERE panel = ANY(%s::text[])", (list(PANELS),))
        return doc_ids_sha256(row[0] for row in rows)

    def exact_matches(self, *, rs, hgvs_c, hgvs_p, genes, query_vector, limit):
        """Cherche les variants par rs ou HGVS exacts, filtrés par gène."""
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
        """Cherche les documents les plus proches, filtrés par gène et signification."""
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
    """Crée le client LLM du profil (OpenRouter ou Groq) ; seule sa clé est exigée."""
    if profile.backend == "openrouter":
        return OpenRouterClient(load_openrouter_key(env), timeout_s=timeout_s)
    if profile.backend == "groq":
        return GroqClient(load_groq_key(env), timeout_s=timeout_s)
    raise RagConfigurationError(f"profil {profile.name} : backend {profile.backend!r} inconnu")


class Searcher:
    """Recherche câblée sur les services réels, après vérification du modèle d'embedding (empreinte et canari)."""

    def __init__(self, *, profile_name: str | None = None, cache_path: Path | None = None,
                 config_path: Path = DEFAULT_CONFIG_PATH, env=None, analysis_client=None) -> None:
        """`analysis_client` remplace le client LLM (rejeu hors ligne, sans clé)."""
        rag = load_config(config_path)
        self.config: SearchConfig = load_search_config(config_path, profile_name)
        services = load_service_settings(env)
        check_served_model(rag.embedding.fingerprint, served_fingerprint(services.served_model_dir))
        self._embedder = EmbeddingClient(services.embeddings_url, services.embeddings_api_key,
                                         timeout_s=rag.embedding.request_timeout_s)
        self._fingerprint = rag.embedding.fingerprint
        verify_canary(self._embedder, load_canary(rag.embedding.canary_path), rag.embedding.fingerprint,
                      rag.embedding.canary_min_cosine)
        self._llm = (analysis_client if analysis_client is not None
                     else build_llm_client(self.config.analysis_profile, env, self.config.llm_timeout_s))
        self._cache = AnalysisCache(cache_path) if cache_path else None
        self._store = PgSearchStore(services.pg_conninfo)
        self._settings = SearchSettings(self.config.k, self.config.min_filtered, self.config.max_question_chars)
        self._indexed = False

    def __enter__(self) -> Self:
        # Index vide accepté (installation neuve) : l'API démarre et Airflow peut l'indexer ; autre modèle refusé.
        self._store.__enter__()
        try:
            self._indexed = check_index_models(self._store.index_models(), self._fingerprint)
        except BaseException:
            self._store.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        try:
            self._store.__exit__(*exc_info)
        finally:
            self.close()

    def close(self) -> None:
        """Ferme les sessions HTTP de l'embedding et du LLM."""
        try:
            self._embedder.close()
        finally:
            self._llm.close()

    def index_doc_ids_sha256(self) -> str:
        """Renvoie l'empreinte des documents de l'index."""
        return self._store.doc_ids_sha256()

    def _require_index(self) -> None:
        """Revérifie un index vide jusqu'à ce qu'il soit rempli, puis plus jamais."""
        if not self._indexed:
            self._indexed = check_index_models(self._store.index_models(), self._fingerprint)
        if not self._indexed:
            raise IndexEmptyError("index vide : lancer l'indexation (DAG de panel) avant toute recherche")

    def search(self, question: str, mode: str = "full", force_exact: bool | None = None) -> SearchResult:
        """Cherche les documents d'une question avec les services réels."""
        self._require_index()
        profile = self.config.analysis_profile
        return search(
            question, settings=self._settings, store=self._store, mode=mode, force_exact=force_exact,
            analyze=lambda q: analyze(q, client=self._llm, profile=profile,
                                      max_tokens=self.config.llm_max_tokens, cache=self._cache),
            embed=lambda text: self._embedder.embed([text])[0],
        )
