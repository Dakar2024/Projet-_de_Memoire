"""Évaluation de la génération et choix du modèle (E3a).
Spec : docs/superpowers/specs/2026-10-14-sous-projet-e3a-evaluation-generation-design.md

  tirer           sur l'hôte : tire le jeu de questions dans le Gold (graine), écrit un brouillon
                  (jamais par-dessus un fichier existant), à relire et rédiger à la main
  verite-terrain  sur l'hôte : documents pertinents de chaque question, par les règles de E1/E2a
  rechercher      dans rag-search : analyse (cache dédié) et recherche, une fois par question
  lancer          dans rag-search : génération par un candidat sur les recherches figées
  juger           dans rag-search : fidélité et pertinence par le juge (verdicts en cache)
  echantillonner  n'importe où : 40 réponses tirées pour l'annotation humaine en aveugle
  annoter         sur l'hôte : annotation dans le terminal, reprise possible
  evaluer         n'importe où : métriques, kappas, règle de choix ; refuse de conclure s'il
                  manque quelque chose ou si deux séries divergent

Toutes les sorties vont dans data/experiments/e3a (non versionné), écrites de façon atomique.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import yaml

_ROOT = Path(__file__).resolve().parents[2]  # racine du dépôt, ou /opt/projet dans le conteneur
EXPERIMENTS = Path(__file__).resolve().parent
QUESTIONS_PATH = EXPERIMENTS / "questions_evaluation_e3a.yaml"
QUESTIONS_E2A = EXPERIMENTS / "questions_recherche.yaml"
OUT = _ROOT / "data" / "experiments" / "e3a"

STRATA = ("I", "S", "G", "M")
# Libellés ClinVar exacts par classe : mêmes listes que les règles de E1/E2a (famille C).
SIGNIFICANCE_CLASSES = {
    "pathogenic": ["Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic"],
    "benign": ["Benign", "Likely benign", "Benign/Likely benign"],
    "uncertain": ["Uncertain significance"],
    "conflicting": ["Conflicting classifications of pathogenicity"],
}
_CLASS_FR = {"pathogenic": "pathogènes", "benign": "bénins", "uncertain": "de signification incertaine",
             "conflicting": "aux interprétations contradictoires"}
# Noms de maladie sans contenu : ils ne font pas une question (spec §4.1).
# Syntaxe commune à Python et à Polars (moteur regex de Rust) : drapeau (?i) en tête.
_UNINFORMATIVE = r"(?i)^(?:not provided|not specified|see cases|\d+ conditions)$"
_I_TEMPLATES = (
    "Que sait-on du variant {v} de {g} ?",
    "Quelle est la signification clinique du variant {v} de {g} ?",
    "À quelles maladies le variant {v} de {g} est-il associé ?",
    "Quel est le statut de revue du variant {v} de {g} ?",
)
_MAX_ATTEMPTS = 200
UNAVAILABLE = "generation_unavailable"
SEARCHES = OUT / "recherches.json"
TRUTH = OUT / "verite_terrain.json"
ANALYSIS_CACHE = OUT / "cache_analyses.json"
GENERATION_CACHE = OUT / "cache_generation.json"
SPENDING = OUT / "depenses.json"
JUDGEMENTS = OUT / "jugements.json"
JUDGE_CACHE = OUT / "cache_juge.json"
SAMPLE = OUT / "echantillon.json"
ANNOTATIONS = OUT / "annotations.json"
GENERATIONS = OUT / "generations"
EVALUATION = OUT / "evaluation.json"
_ABSTENTIONS = ("not_in_sources", "out_of_scope")
_JUDGED_STATUSES = ("answered", "partial")
# Délai par appel au juge : sa réflexion interne sur 10 fiches dépasse parfois la minute.
_JUDGE_TIMEOUT_S = 120.0


def _write_json_atomic(path: Path, data) -> None:
    """Fichier temporaire puis renommage : un arrêt ne laisse jamais un fichier tronqué."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Tirage du jeu (spec §4.1) ---------------------------------------------------------------

def _pick(rng: np.random.Generator, items: list):
    return items[int(rng.integers(0, len(items)))]


def _informative_diseases(documents, diseases):
    """(doc_id, gène, signification, maladie) pour les documents de variant, sans les noms vides."""
    import polars as pl
    names = diseases.filter(~pl.col("disease_name").str.contains(_UNINFORMATIVE))
    return names.join(documents.filter(pl.col("doc_type") == "variant")
                      .select("doc_id", "gene_symbol", "clinical_significance"), on="doc_id")


def _significance_class(label: str | None) -> str | None:
    for name, labels in SIGNIFICANCE_CLASSES.items():
        if label in labels:
            return name
    return None


def _draw_identifier(rng, variants, genes, used: set[str], excluded: set[str], index: int) -> dict:
    import polars as pl
    for _ in range(_MAX_ATTEMPTS):
        gene = _pick(rng, genes)
        pool = (variants.filter((pl.col("gene_symbol") == gene) & ~pl.col("doc_id").is_in(sorted(used | excluded))
                                & ((pl.col("rs_dbsnp") > 0) | pl.col("hgvs_c").is_not_null()))
                .sort("doc_id"))
        if pool.height == 0:
            continue
        row = pool.row(int(rng.integers(0, pool.height)), named=True)
        rs_ok, hgvs_ok = (row["rs_dbsnp"] or -1) > 0, row["hgvs_c"] is not None
        use_rs = rs_ok if index % 2 == 0 else not hgvs_ok
        variant = f"rs{row['rs_dbsnp']}" if use_rs else row["hgvs_c"]
        used.add(row["doc_id"])
        return {"tirage": {"gene": gene, "doc_id": row["doc_id"], "identifiant": variant},
                "question": _I_TEMPLATES[index % len(_I_TEMPLATES)].format(v=variant, g=gene),
                "relevant": {"identifiers": True}}
    raise RuntimeError("tirage I : aucun variant tirable après de nombreux essais")


def _draw_disease(rng, table, genes, used: set[tuple], *, with_class: bool) -> dict:
    import polars as pl
    for _ in range(_MAX_ATTEMPTS):
        gene = _pick(rng, genes)
        rows = table.filter(pl.col("gene_symbol") == gene)
        names = sorted(rows["disease_name"].unique().to_list())
        if not names:
            continue
        disease = _pick(rng, names)
        relevant: dict = {"gene": gene, "disease_pattern": disease.lower()}
        tirage: dict = {"gene": gene, "maladie": disease}
        key: tuple = (gene, disease.lower())
        if with_class:
            present = sorted({c for c in (_significance_class(s) for s in
                                          rows.filter(pl.col("disease_name") == disease)["clinical_significance"])
                              if c is not None})
            if not present:
                continue
            cls = _pick(rng, present)
            relevant["significance"] = SIGNIFICANCE_CLASSES[cls]
            tirage["classe"] = cls
            key += (cls,)
            question = f"Quels variants {_CLASS_FR[cls]} de {gene} sont rapportés pour « {disease} » ?"
        else:
            question = f"Quels variants de {gene} sont associés à « {disease} » ?"
        if key in used:
            continue
        used.add(key)
        return {"tirage": tirage, "question": question, "relevant": relevant}
    raise RuntimeError("tirage S/M : aucun couple gène-maladie tirable après de nombreux essais")


def draw_questions(documents, diseases, *, strata: dict[str, int], seed: int,
                   excluded_doc_ids: set[str]) -> list[dict]:
    """Tirage déterministe (graine) du jeu, strate par strate, dans l'ordre I, S, M, G.
    `documents` : Gold (colonnes de RAG.src.ingestion.loader) ; `diseases` : (doc_id, disease_name)."""
    import polars as pl
    rng = np.random.default_rng(seed)
    variants = documents.filter(pl.col("doc_type") == "variant")
    variant_genes = sorted(variants["gene_symbol"].unique().to_list())
    table = _informative_diseases(documents, diseases)
    disease_genes = sorted(table["gene_symbol"].unique().to_list())
    gene_docs = sorted(documents.filter(pl.col("doc_type") == "gene")["gene_symbol"].to_list())
    out: list[dict] = []

    used_docs: set[str] = set()
    for i in range(strata["I"]):
        out.append({"id": f"E3-I{i + 1:02d}", "strate": "I",
                    **_draw_identifier(rng, variants, variant_genes, used_docs, excluded_doc_ids, i)})
    used_pairs: set[tuple] = set()
    for i in range(strata["S"]):
        out.append({"id": f"E3-S{i + 1:02d}", "strate": "S",
                    **_draw_disease(rng, table, disease_genes, used_pairs, with_class=True)})
    used_pairs = {key[:2] for key in used_pairs}  # une maladie de S n'est pas reprise en M
    for i in range(strata["M"]):
        out.append({"id": f"E3-M{i + 1:02d}", "strate": "M",
                    **_draw_disease(rng, table, disease_genes, used_pairs, with_class=False)})
    if strata["G"] > len(gene_docs):
        raise RuntimeError("tirage G : plus de questions que de documents de gène")
    for i, index in enumerate(rng.choice(len(gene_docs), size=strata["G"], replace=False)):
        gene = gene_docs[int(index)]
        out.append({"id": f"E3-G{i + 1:02d}", "strate": "G", "tirage": {"gene": gene},
                    "question": f"Quel est le rôle du gène {gene} ?", "relevant": {"doc_id": f"gene:{gene}"}})
    return out


def render_draft(questions: list[dict], *, seed: int) -> str:
    """Brouillon YAML : une question par ligne (objet JSON, donc YAML valide), en-tête commenté."""
    header = (f"# Jeu de l'évaluation E3a (spec §4). Tiré avec la graine {seed} ; brouillon de `tirer`.\n"
              "# Rédiger chaque question en français naturel SANS changer les valeurs de `tirage`.\n"
              "# Écarter une question : ajouter `ecartee: \"motif\"` (elle reste dans le fichier).\n")
    lines = []
    for strate in STRATA:
        lines.append(f"\n# --- Strate {strate} ---")
        lines += [f"- {json.dumps(q, ensure_ascii=False)}" for q in questions if q["strate"] == strate]
    return header + "\n".join(lines) + "\n"


# --- Chargement et contrôles du jeu (spec §4.2) ---------------------------------------------

def load_questions(path: Path, strata: dict[str, int]) -> list[dict]:
    """Questions actives (non écartées). Refuse un jeu non conforme : effectifs, identifiants,
    question hors périmètre, strate I dont le texte ne cite plus le variant tiré."""
    from RAG.src.generation.scope import detect_out_of_scope
    from RAG.src.retrieval.identifiers import extract_identifiers

    items = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(items, list) or not all(isinstance(q, dict) for q in items):
        raise SystemExit(f"{path.name} : liste de questions attendue")
    ids = [q.get("id") for q in items]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SystemExit(f"{path.name} : identifiants en double {duplicates}")
    counts = {s: sum(1 for q in items if q.get("strate") == s) for s in STRATA}
    if counts != strata or len(items) != sum(strata.values()):
        raise SystemExit(f"{path.name} : effectifs {counts}, attendus {strata}")
    active = []
    for q in items:
        if not {"id", "strate", "question", "tirage", "relevant"} <= set(q):
            raise SystemExit(f"{q.get('id')} : champs manquants")
        if q.get("ecartee") is not None:
            if not (isinstance(q["ecartee"], str) and q["ecartee"].strip()):
                raise SystemExit(f"{q['id']} : une question écartée porte un motif écrit")
            continue
        reason = detect_out_of_scope(q["question"])
        if reason is not None:
            raise SystemExit(f"{q['id']} : classée hors périmètre ({reason}) — elle ne mesurerait pas la génération")
        if q["strate"] == "I":
            ids_found = extract_identifiers(q["question"])
            drawn = q["tirage"]["identifiant"]
            cited = {f"rs{r}" for r in ids_found.rs} | set(ids_found.hgvs_c)
            if drawn not in cited or q["tirage"]["gene"] not in ids_found.genes:
                raise SystemExit(f"{q['id']} : le texte ne cite plus {drawn} et {q['tirage']['gene']}")
        active.append(q)
    return active


def relevant_doc_ids(question: dict, documents, diseases) -> list[str]:
    """Documents pertinents : correspondance exacte (strate I, même sémantique que la recherche),
    sinon la règle `_relevance` de E1/E2a."""
    if question["strate"] == "I":
        from RAG.experiments.mesure_recherche import exact_doc_ids
        from RAG.src.retrieval.identifiers import extract_identifiers
        found = exact_doc_ids(documents, extract_identifiers(question["question"]))
        if question["tirage"]["doc_id"] not in found:
            raise SystemExit(f"{question['id']} : le variant tiré n'est pas retrouvé par la correspondance exacte")
        return sorted(found)
    from RAG.experiments.comparaison_embeddings import _relevance
    mask = _relevance(question, documents, diseases)
    doc_ids = documents["doc_id"].to_list()
    relevant = [doc_ids[i] for i in np.flatnonzero(mask)]
    if not relevant:
        raise SystemExit(f"{question['id']} : aucun document pertinent dans le Gold")
    return relevant



# --- Clients enveloppés : budget, cache, enregistrement (spec §5.1, §9) ------------------------

class BudgetExceededError(Exception):
    """Le prochain appel payant pourrait dépasser le plafond de dépense."""


class Budget:
    """Dépense réelle cumulée (`usage.cost` de chaque appel payé), persistée de façon atomique.
    `check` refuse un appel si dépensé + réserve dépasse le plafond : la réserve couvre le coût
    maximal d'un appel au plafond de jetons, donc le plafond n'est jamais franchi.

    Un verrou exclusif (fichier `.lock` à côté) est pris pour toute la vie de l'objet : deux
    commandes payantes simultanées liraient le même total et le plafond pourrait être dépassé."""

    def __init__(self, path: Path, limit_usd: float, reserve_usd: float) -> None:
        import fcntl
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = open(path.with_name(path.name + ".lock"), "w")  # noqa: SIM115 - gardé ouvert
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise SystemExit("une autre commande payante de E3a est en cours : attendre qu'elle se termine") from None
        self._path, self.limit, self.reserve = path, limit_usd, reserve_usd
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.spent = float(data.get("total_usd", 0.0))
        self.calls = int(data.get("appels", 0))

    def close(self) -> None:
        """Libère le verrou (la fermeture du fichier relâche `flock`)."""
        self._lock.close()

    def check(self) -> None:
        if self.spent + self.reserve > self.limit:
            raise BudgetExceededError(f"plafond de dépense : {self.spent:.4f} $ dépensés, réserve "
                                      f"{self.reserve} $, plafond {self.limit} $")

    def spend(self, cost_usd: float | None) -> None:
        self.calls += 1
        self.spent += float(cost_usd or 0.0)
        _write_json_atomic(self._path, {"total_usd": self.spent, "appels": self.calls})


class BudgetedClient:
    """Client réel sous plafond : vérifie avant, compte après. Une coupure facturée
    (`LlmTruncatedError.cost_usd`) est comptée. Limite : une réponse rejetée par le client après
    facturation (fournisseur inattendu, coût absent) n'a pas de coût lisible ; la réserve la couvre."""

    def __init__(self, inner, budget: Budget) -> None:
        self._inner, self._budget = inner, budget

    def complete_json(self, profile, **kwargs):
        from RAG.src.utils.errors import LlmTruncatedError
        self._budget.check()
        try:
            call = self._inner.complete_json(profile, **kwargs)
        except LlmTruncatedError as exc:
            self._budget.spend(exc.cost_usd)
            raise
        self._budget.spend(call.cost_usd)
        return call

    def close(self) -> None:
        try:
            self._inner.close()
        finally:
            self._budget.close()


def call_cache_key(namespace: str, profile, *, system: str, user: str, schema_name: str, max_tokens: int) -> str:
    """Clé d'un appel : espace (passage de génération, passage du juge), modèle, point d'accès,
    plafond, schéma, prompt système et message exacts. Un changement de prompt change la clé."""
    payload = json.dumps([namespace, profile.model, profile.provider_tag, max_tokens, schema_name, system, user],
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedClient:
    """Cache disque des appels réussis : une reprise ne repaie rien. Les échecs ne sont jamais
    mis en cache. `last_hit` dit si le dernier appel vient du cache (latence non mesurée)."""

    def __init__(self, inner, path: Path, namespace: str) -> None:
        self._inner, self._path, self._namespace = inner, path, namespace
        self._cache: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.last_hit = False
        self._last_key: str | None = None

    def forget_last(self) -> None:
        """Retire le dernier appel du cache : sa sortie a été refusée après coup (jugement
        incohérent). Sans cela, la reprise relirait indéfiniment la même sortie refusée."""
        if self._last_key is not None and self._cache.pop(self._last_key, None) is not None:
            _write_json_atomic(self._path, self._cache)
        self._last_key = None

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
        from RAG.src.llm.common import LlmCall
        key = call_cache_key(self._namespace, profile, system=system, user=user, schema_name=schema_name,
                             max_tokens=max_tokens)
        self._last_key = key
        if key in self._cache:
            self.last_hit = True
            return LlmCall(**self._cache[key])
        self.last_hit = False
        call = self._inner.complete_json(profile, system=system, user=user, schema_name=schema_name,
                                         schema=schema, max_tokens=max_tokens)
        self._cache[key] = {"content": call.content, "generation_id": call.generation_id,
                            "provider_name": call.provider_name, "cost_usd": call.cost_usd,
                            "prompt_tokens": call.prompt_tokens, "completion_tokens": call.completion_tokens}
        _write_json_atomic(self._path, self._cache)
        return call

    def close(self) -> None:
        self._inner.close()


class RecordingClient:
    """Garde le contenu brut du dernier appel : la réponse du modèle AVANT les contrôles de E2b,
    même quand ils la rejettent, sans toucher au code gelé."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.last_content: dict | None = None

    def complete_json(self, profile, **kwargs):
        self.last_content = None
        call = self._inner.complete_json(profile, **kwargs)
        self.last_content = call.content
        return call

    def close(self) -> None:
        self._inner.close()


class _WouldCallLlm(Exception):
    pass


class ProbeClient:
    """Sonde de `rechercher` : lève dès que la génération appellerait le LLM. Les cas à message
    fixe (hors périmètre par règles, identifiant introuvable, aucun document) sont ainsi décidés
    par le code gelé de E2b lui-même, sans le recopier."""

    def complete_json(self, *args, **kwargs):
        raise _WouldCallLlm

    def close(self) -> None:
        pass


class OfflineAnalysisClient:
    """`lancer` refait la recherche avec les analyses en cache seulement : aucune analyse payée."""

    def complete_json(self, *args, **kwargs):
        from RAG.src.utils.errors import LlmUnavailableError
        raise LlmUnavailableError("analyse absente du cache de E3a : relancer `rechercher`")

    def close(self) -> None:
        pass


def select_repeats(llm_ids: list[str], n: int, seed: int) -> list[str]:
    """Questions reprises (spec §5.2) : n tirées sans remise parmi celles où le LLM est appelé."""
    if n > len(llm_ids):
        raise SystemExit(f"{n} reprises demandées pour {len(llm_ids)} questions où le LLM est appelé")
    rng = np.random.default_rng(seed)
    ordered = sorted(llm_ids)
    return sorted(ordered[int(i)] for i in rng.choice(len(ordered), size=n, replace=False))


def generation_record(question: dict, answer, raw: dict | None, *, passage: int, from_cache: bool) -> dict:
    """Enregistrement d'une génération : statut livré ET réponse brute du modèle (statut, texte,
    citations), pour juger le modèle et non le filtre."""
    from RAG.src.generation.answer import validate_generation
    record = {"id": question["id"], "strate": question["strate"], "passage": passage,
              "status": answer.status, "rejected": answer.rejected, "cost_usd": answer.cost_usd,
              "latency_ms": answer.latency_ms, "from_cache": from_cache, "provider_name": answer.provider_name,
              "model": answer.model, "llm_status": None, "llm_text": None, "llm_citations": []}
    if raw is not None:
        status, _reason, text, citations = validate_generation(raw)
        record.update(llm_status=status, llm_text=text, llm_citations=citations)
    return record


def unavailable_record(question: dict, error: Exception, *, passage: int) -> dict:
    """Génération indisponible : seul le nom de la classe d'erreur, jamais son texte."""
    return {"id": question["id"], "strate": question["strate"], "passage": passage, "status": UNAVAILABLE,
            "error": type(error).__name__, "rejected": None, "cost_usd": 0.0, "latency_ms": None,
            "from_cache": False, "llm_status": None, "llm_text": None, "llm_citations": []}


def check_same_documents(question_id: str, stored: list[str], found: list[str]) -> None:
    if stored != found:
        raise SystemExit(f"{question_id} : la recherche ne redonne pas les documents de recherches.json "
                         "(index ou analyse changés) — aucune génération lancée")


def check_manifest(path: Path, expected: dict, found: dict) -> None:
    if found != expected:
        diff = sorted(k for k in set(expected) | set(found) if expected.get(k) != found.get(k))
        raise SystemExit(f"{path.name} : conditions différentes de la série en cours ({', '.join(diff)}) — "
                         "ne pas mêler deux séries ; archiver le fichier pour recommencer")



def search_record(question: dict, result, *, profile, max_tokens: int) -> dict:
    """Recherche figée d'une question : documents transmis, contexte exact rendu pour le LLM
    (celui que verra le juge), et si la génération appellera le LLM (sonde, §5.1)."""
    from RAG.src.generation.answer import generate_answer
    from RAG.src.generation.context import build_context
    try:
        fixed = generate_answer(question["question"], result, client=ProbeClient(), profile=profile,
                                max_tokens=max_tokens)
        llm_called, fixed_status = False, fixed.status
    except _WouldCallLlm:
        llm_called, fixed_status = True, None
    analysis = result.trace.analysis
    return {"id": question["id"], "strate": question["strate"], "doc_ids": [d.doc_id for d in result.documents],
            "context": build_context(result.documents), "flags": list(result.trace.flags),
            "llm_called": llm_called, "fixed_status": fixed_status,
            "analysis": {"profile": analysis.profile, "english_query": analysis.english_query,
                         "significance": analysis.significance, "cost_usd": analysis.cost_usd}}


def generate_record(question: dict, stored: dict, result, *, recorder: RecordingClient, cached: CachedClient,
                    profile, max_tokens: int, passage: int) -> dict:
    """Une génération sur la recherche figée. Refuse (SystemExit) si les documents ont changé ;
    une génération indisponible est consignée ; budget et refus permanents remontent."""
    from RAG.src.generation.answer import generate_answer
    from RAG.src.utils.errors import LlmUnavailableError
    if not result.trace.analysis.available:
        raise SystemExit(f"{question['id']} : analyse absente du cache — relancer `rechercher`")
    check_same_documents(question["id"], stored["doc_ids"], [d.doc_id for d in result.documents])
    cached.last_hit = False
    try:
        answer = generate_answer(question["question"], result, client=recorder, profile=profile, max_tokens=max_tokens)
    except LlmUnavailableError as exc:
        return unavailable_record(question, exc, passage=passage)
    if not answer.from_llm:
        raise SystemExit(f"{question['id']} : message fixe alors que `rechercher` prévoyait un appel au LLM")
    return generation_record(question, answer, recorder.last_content, passage=passage, from_cache=cached.last_hit)



# --- Jugement, échantillon, annotation (spec §6, §7) -------------------------------------------

def judge_key(profile: str, passage: int, question_id: str, repetition: int = 1) -> str:
    """Clé d'un jugement ; la répétition 2 est le rejugement de l'échantillon (stabilité du juge)."""
    return f"{profile}|p{passage}|{question_id}|r{repetition}"


def parse_judge_key(key: str) -> tuple[str, int, str, int]:
    profile, passage, question_id, repetition = key.split("|")
    return profile, int(passage[1:]), question_id, int(repetition[1:])


def judgeable(record: dict) -> bool:
    """Réponse jugée : le modèle a répondu (answered/partial) avec un texte, avant les contrôles."""
    return record.get("llm_status") in _JUDGED_STATUSES and bool((record.get("llm_text") or "").strip())


def load_generations(folder: Path = None) -> dict[tuple[str, int], dict]:
    folder = folder or GENERATIONS
    out = {}
    for path in sorted(folder.glob("*__p*.json")) if folder.exists() else []:
        data = json.loads(path.read_text(encoding="utf-8"))
        out[(data["manifest"]["profile"], int(data["manifest"]["passage"]))] = data
    return out


def answers_to_judge(generations: dict[tuple[str, int], dict]) -> list[tuple[str, dict]]:
    """(clé, enregistrement) de chaque réponse à juger, tous candidats et passages."""
    return [(judge_key(profile, passage, qid), record)
            for (profile, passage), data in sorted(generations.items())
            for qid, record in sorted(data["records"].items()) if judgeable(record)]


def _allocate(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Répartition proportionnelle à plus fort reste (déterministe : égalités par nom)."""
    whole = sum(weights.values())
    if whole == 0:
        return {k: 0 for k in weights}
    exact = {k: total * w / whole for k, w in weights.items()}
    out = {k: int(v) for k, v in exact.items()}
    for k in sorted(weights, key=lambda k: (-(exact[k] - out[k]), k))[:total - sum(out.values())]:
        out[k] += 1
    return out


def draw_sample(eligible: list[dict], *, size: int, seed: int, candidates: tuple[str, ...]) -> list[str]:
    """Échantillon d'annotation (spec §7.1) : `size` réponses réparties entre candidats (reste aux
    premiers : 14/13/13), puis proportionnellement aux strates ; ordre de présentation aléatoire.
    `eligible` : {"key", "profile", "strate"} des réponses jugées ayant au moins une affirmation."""
    rng = np.random.default_rng(seed)
    base, extra = divmod(size, len(candidates))
    chosen: list[str] = []
    for i, candidate in enumerate(candidates):
        quota = base + (1 if i < extra else 0)
        mine = sorted((e for e in eligible if e["profile"] == candidate), key=lambda e: e["key"])
        if len(mine) < quota:
            raise SystemExit(f"{candidate} : {len(mine)} réponse(s) jugée(s) avec affirmations, {quota} requises")
        strata = sorted({e["strate"] for e in mine})
        per_stratum = _allocate(quota, {s: sum(e["strate"] == s for e in mine) for s in strata})
        for stratum in strata:
            pool = [e["key"] for e in mine if e["strate"] == stratum]
            chosen += [pool[int(j)] for j in rng.choice(len(pool), size=per_stratum[stratum], replace=False)]
    return [chosen[int(j)] for j in rng.permutation(len(chosen))]


_CONTROL = {c: None for c in range(32) if c not in (9, 10)} | {127: None} | {c: None for c in range(128, 160)}


def _safe(text: str) -> str:
    """Retire les caractères de contrôle (sauf tabulation et saut de ligne) avant affichage : une
    fiche ou une réponse de modèle contenant une séquence d'échappement ANSI ne doit pas agir sur
    le terminal de l'annotateur."""
    return text.translate(_CONTROL)


def _readable(context: str) -> str:
    from html import unescape
    return _safe(unescape(context))


def annotate(items: list[dict], done: dict, *, ask, show, save) -> dict:
    """Annotation en aveugle. `items` : {"n", "question", "context", "answer", "claims"} — ni
    candidat ni verdict du juge. Saisie : par affirmation `s` (soutenue) ou `n` (non soutenue),
    suivie de `m` si elle est mal découpée ; puis affirmation oubliée (o/n) ; puis pertinence 0/1/2.
    `q` arrête (tout ce qui est fini est déjà enregistré). Une saisie invalide est redemandée."""
    def prompt(text: str, valid: set[str]) -> str:
        while True:
            value = ask(text).strip().lower()
            if value == "q":
                raise KeyboardInterrupt
            if value in valid:
                return value
            show(f"  saisie attendue : {', '.join(sorted(valid))} (ou q pour arrêter)")

    total = len(items)
    try:
        for item in items:
            key = str(item["n"])
            if key in done:
                continue
            show(f"\n===== Réponse {item['n']}/{total} =====\nQUESTION : {_safe(item['question'])}\n\n"
                 f"DOCUMENTS :\n{_readable(item['context'])}\n\nRÉPONSE :\n{_safe(item['answer'])}\n\nAFFIRMATIONS :")
            verdicts, badly_split = [], []
            for i, claim in enumerate(item["claims"], start=1):
                show(f"  {i}. {_safe(claim)}")
                value = prompt(f"  {i} soutenue (s) / non soutenue (n), + m si mal découpée : ",
                               {"s", "n", "sm", "nm"})
                verdicts.append(value[0] == "s")
                if value.endswith("m"):
                    badly_split.append(i)
            missed = prompt("Une affirmation de la réponse a-t-elle été oubliée ? (o/n) : ", {"o", "n"}) == "o"
            relevance = int(prompt("Pertinence : 2 traite la question, 1 en partie, 0 non : ", {"0", "1", "2"}))
            done[key] = {"verdicts": verdicts, "mal_decoupees": badly_split, "oubliee": missed,
                         "pertinence": relevance}
            save(done)
    except KeyboardInterrupt:
        show("\narrêt : les réponses terminées sont enregistrées ; relancer `annoter` pour reprendre")
    return done



# --- Évaluation (spec §6, §7.3, §8) --------------------------------------------------------------

def retrieval_metrics(searches: dict[str, dict], relevant: dict[str, list[str]], strata: dict[str, str],
                      k: int) -> dict[str, dict]:
    """Par strate : précision (pertinents transmis / transmis), rappel@k (pertinents transmis /
    min(|pertinents|, k)), et pour la strate I la part des questions dont le 1er document est pertinent."""
    by_stratum: dict[str, dict[str, list[float]]] = {}
    for qid, record in searches.items():
        sent, rel = record["doc_ids"], set(relevant[qid])
        hits = sum(d in rel for d in sent)
        bucket = by_stratum.setdefault(strata[qid], {"precision": [], "rappel": [], "premier": []})
        bucket["precision"].append(hits / len(sent) if sent else 0.0)
        bucket["rappel"].append(hits / min(len(rel), k) if rel else 0.0)
        bucket["premier"].append(1.0 if sent and sent[0] in rel else 0.0)
    out = {}
    for stratum, values in sorted(by_stratum.items()):
        out[stratum] = {"n": len(values["precision"]), "precision": float(np.mean(values["precision"])),
                        "rappel": float(np.mean(values["rappel"]))}
        if stratum == "I":
            out[stratum]["premier_pertinent"] = float(np.mean(values["premier"]))
    return out


def candidate_result(profile: str, generations: dict[tuple[str, int], dict], judgements: dict[str, dict],
                     searches: dict[str, dict], relevant: dict[str, list[str]], passes: int):
    """Mesures d'un candidat (spec §6.3). Dénominateur : questions du passage 1 où le LLM est appelé."""
    from RAG.src.evaluation.decision import CandidateResult
    records = generations[(profile, 1)]["records"]
    n = len(records)
    rejected = sum(r["status"] in ("unverifiable", UNAVAILABLE) for r in records.values())
    unavailable = sum(r["status"] == UNAVAILABLE for r in records.values())
    wrong_abstentions = sum(1 for qid, r in records.items() if r["llm_status"] in _ABSTENTIONS
                            and set(searches[qid]["doc_ids"]) & set(relevant[qid]))
    faithfulness, relevance = {}, {}
    for qid in records:
        judged = judgements.get(judge_key(profile, 1, qid))
        if judged is None:
            continue
        relevance[qid] = judged["relevance"] / 2
        if judged["faithfulness"] is not None:
            faithfulness[qid] = judged["faithfulness"]
    # Variabilité : les questions reprises (passages 2 et suivants), notées sur chacun des passages.
    repeat_ids = sorted(generations[(profile, 2)]["records"]) if (profile, 2) in generations else []
    repeat_f: dict[str, list[float]] = {}
    repeat_r: dict[str, list[float]] = {}
    for passage in range(1, passes + 1):
        for qid in repeat_ids:
            judged = judgements.get(judge_key(profile, passage, qid))
            if judged is None:
                continue
            repeat_r.setdefault(qid, []).append(judged["relevance"] / 2)
            if judged["faithfulness"] is not None:
                repeat_f.setdefault(qid, []).append(judged["faithfulness"])
    latencies = [r["latency_ms"] for r in records.values() if not r["from_cache"] and r["latency_ms"] is not None]
    result = CandidateResult(
        name=profile, faithfulness=faithfulness, relevance=relevance,
        rejection_rate=rejected / n if n else 1.0, wrong_abstention_rate=wrong_abstentions / n if n else 0.0,
        mean_cost=float(np.mean([r["cost_usd"] for r in records.values()])) if n else 0.0,
        median_latency_ms=float(np.median(latencies)) if latencies else float("inf"),
        repeat_faithfulness=repeat_f, repeat_relevance=repeat_r)
    statuses: dict[str, int] = {}
    for r in records.values():
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    details = {"questions": n, "rejets_controles": rejected - unavailable, "indisponibles": unavailable,
               "abstentions_a_tort": wrong_abstentions, "reponses_jugees": len(relevance),
               "sans_affirmation": len(relevance) - len(faithfulness), "statuts": statuses,
               "latence_mesuree_sur": len(latencies)}
    return result, details


def completeness_problems(candidates: tuple[str, ...], generations: dict[tuple[str, int], dict],
                          judgements: dict[str, dict], llm_ids: list[str], repeat_ids: list[str],
                          passes: int) -> list[str]:
    """Tout ce qui manque pour conclure (spec §12) ; vide si rien ne manque."""
    problems = []
    for profile in candidates:
        for passage in range(1, passes + 1):
            expected = llm_ids if passage == 1 else repeat_ids
            data = generations.get((profile, passage))
            got = set(data["records"]) if data else set()
            missing = sorted(set(expected) - got)
            if missing:
                problems.append(f"{profile} passage {passage} : {len(missing)} génération(s) manquante(s)")
            for qid in sorted(got & set(expected)):
                if judgeable(data["records"][qid]) and judge_key(profile, passage, qid) not in judgements:
                    problems.append(f"{profile} passage {passage} : jugement manquant pour {qid}")
    return problems


def manifest_problems(searches_manifest: dict, generations: dict[tuple[str, int], dict]) -> list[str]:
    """Toutes les séries doivent porter les mêmes conditions que les recherches figées."""
    shared = ("questions_sha256", "index_doc_ids_sha256", "analysis_profile", "generation_prompt_sha",
              "generation_max_tokens", "settings_sha256")
    reference: dict = {}
    problems = []
    for (profile, passage), data in sorted(generations.items()):
        m = data["manifest"]
        for key in ("questions_sha256", "index_doc_ids_sha256", "analysis_profile"):
            if m.get(key) != searches_manifest.get(key):
                problems.append(f"{profile} passage {passage} : {key} différent des recherches")
        for key in shared:
            reference.setdefault(key, m.get(key))
            if m.get(key) != reference[key]:
                problems.append(f"{profile} passage {passage} : {key} différent des autres séries")
    return problems


def _mean_or_none(values: list[float]) -> float | None:
    """Moyenne, ou None sans valeur (jamais NaN : le rapport reste du JSON standard)."""
    return float(np.mean(values)) if values else None


def agreement_report(sample: list[str], annotations: dict, judgements: dict[str, dict], *, seed: int) -> dict:
    """Kappas juge/humain (fidélité par affirmation, pertinence pondérée), IC par grappes,
    signalements de découpage, stabilité du juge (répétition 2), fidélité humaine par candidat."""
    from RAG.src.evaluation.agreement import cluster_bootstrap_ci, cohen_kappa, weighted_kappa
    from RAG.src.evaluation.decision import bootstrap_mean_ci
    yes_no, notes = (True, False), (0, 1, 2)
    faith_clusters, relevance_clusters, human_by_profile = [], [], {}
    badly_split = missed = 0
    for n, key in enumerate(sample, start=1):
        human, judged = annotations[str(n)], judgements[key]
        if len(human["verdicts"]) != len(judged["verdicts"]):
            raise SystemExit(f"annotation {n} : {len(human['verdicts'])} verdicts pour "
                             f"{len(judged['verdicts'])} affirmations")
        faith_clusters.append(list(zip(judged["verdicts"], human["verdicts"])))
        relevance_clusters.append([(judged["relevance"], human["pertinence"])])
        badly_split += len(human["mal_decoupees"])
        missed += int(human["oubliee"])
        if human["verdicts"]:
            human_by_profile.setdefault(parse_judge_key(key)[0], []).append(
                sum(human["verdicts"]) / len(human["verdicts"]))

    def kappa_f(a, b):
        return cohen_kappa(a, b, yes_no)

    def kappa_r(a, b):
        return weighted_kappa(a, b, notes)

    flat_f = [p for c in faith_clusters for p in c]
    flat_r = [p for c in relevance_clusters for p in c]
    report = {
        "fidelite": {"kappa": kappa_f([p[0] for p in flat_f], [p[1] for p in flat_f]),
                     "ic95": cluster_bootstrap_ci(faith_clusters, kappa_f, seed=seed),
                     "affirmations": len(flat_f)},
        "pertinence": {"kappa_pondere": kappa_r([p[0] for p in flat_r], [p[1] for p in flat_r]),
                       "ic95": cluster_bootstrap_ci(relevance_clusters, kappa_r, seed=seed),
                       "reponses": len(flat_r)},
        "decoupage": {"mal_decoupees": badly_split, "reponses_avec_oubli": missed},
        "fidelite_humaine": {p: dict(zip(("moyenne", "ic_bas", "ic_haut"), bootstrap_mean_ci(v, seed=seed)),
                                     n=len(v)) for p, v in sorted(human_by_profile.items())},
    }
    second = [(judgements[k], judgements.get(k.replace("|r1", "|r2"))) for k in sample]
    pairs = [(a, b) for a, b in second if b is not None]
    if pairs:
        report["stabilite_juge"] = {
            "reponses": len(pairs),
            "kappa_pondere_pertinence": kappa_r([a["relevance"] for a, _ in pairs], [b["relevance"] for _, b in pairs]),
            "ecart_moyen_fidelite": _mean_or_none([abs(a["faithfulness"] - b["faithfulness"]) for a, b in pairs
                                                   if a["faithfulness"] is not None and b["faithfulness"] is not None])}
    return report


# --- Commandes -------------------------------------------------------------------------------

def _e2a_identifier_doc_ids() -> set[str]:
    items = yaml.safe_load(QUESTIONS_E2A.read_text(encoding="utf-8")) or []
    return {d for q in items if q.get("part") == 2 for d in q["relevant"]["doc_ids"]}


def cmd_tirer(args) -> None:
    from RAG.experiments.comparaison_embeddings import _all_documents, _diseases_by_doc
    from RAG.src.evaluation.settings import load_settings
    target = Path(args.sortie) if args.sortie else QUESTIONS_PATH
    if target.exists():
        raise SystemExit(f"{target} existe déjà : le tirage ne l'écrase jamais")
    settings = load_settings()
    questions = draw_questions(_all_documents(), _diseases_by_doc(), strata=settings.strata,
                               seed=settings.seed_draw, excluded_doc_ids=_e2a_identifier_doc_ids())
    target.write_text(render_draft(questions, seed=settings.seed_draw), encoding="utf-8")
    print(f"brouillon : {len(questions)} questions -> {target}")


def cmd_verite_terrain(args) -> None:
    from RAG.experiments.comparaison_embeddings import _all_documents, _diseases_by_doc
    from RAG.src.evaluation.settings import load_settings
    from RAG.src.retrieval.retriever import doc_ids_sha256
    questions = load_questions(QUESTIONS_PATH, load_settings().strata)
    documents, diseases = _all_documents(), _diseases_by_doc()
    relevant = {q["id"]: relevant_doc_ids(q, documents, diseases) for q in questions}
    manifest = {"questions_sha256": _sha256(QUESTIONS_PATH),
                "gold_doc_ids_sha256": doc_ids_sha256(documents["doc_id"].to_list())}
    _write_json_atomic(OUT / "verite_terrain.json", {"manifest": manifest, "relevant": relevant})
    sizes = [len(v) for v in relevant.values()]
    print(f"vérité terrain : {len(relevant)} questions, documents pertinents par question "
          f"médiane {int(np.median(sizes))}, min {min(sizes)}, max {max(sizes)}")


def _manifest_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _load_searches(questions: list[dict]) -> dict:
    data = _manifest_file(SEARCHES)
    missing = sorted({q["id"] for q in questions} - set(data.get("records", {})))
    if not data or missing:
        raise SystemExit(f"recherches incomplètes ({len(missing)} question(s) manquante(s)) : terminer `rechercher`")
    return data


def _stop(exc: Exception) -> SystemExit:
    """Arrêt propre : ce qui est écrit reste valide, la commande reprend où elle s'est arrêtée."""
    return SystemExit(f"arrêt : {exc} — relancer la même commande pour reprendre")


def cmd_rechercher(args) -> None:
    from RAG.experiments.mesure_recherche import config_sha256
    from RAG.src.evaluation.settings import load_settings, settings_sha256
    from RAG.src.retrieval.retriever import Searcher, build_llm_client
    from RAG.src.utils.config import DEFAULT_CONFIG_PATH, load_generation_config, load_search_config
    from RAG.src.utils.errors import LlmPermanentError

    settings = load_settings()
    questions = load_questions(QUESTIONS_PATH, settings.strata)
    truth = _manifest_file(TRUTH).get("manifest")
    if not truth or truth["questions_sha256"] != _sha256(QUESTIONS_PATH):
        raise SystemExit("vérité terrain absente ou calculée sur un autre jeu : lancer `verite-terrain`")
    search_config, generation = load_search_config(), load_generation_config()
    budget = Budget(SPENDING, settings.budget_usd, settings.reserve_per_call_usd)
    client = BudgetedClient(build_llm_client(search_config.analysis_profile, None, search_config.llm_timeout_s), budget)
    with Searcher(cache_path=ANALYSIS_CACHE, analysis_client=client) as searcher:
        index_sha = searcher.index_doc_ids_sha256()
        if index_sha != truth["gold_doc_ids_sha256"]:
            raise SystemExit("l'index ne contient pas les documents de la vérité terrain : relancer "
                             "`verite-terrain` sur le Gold indexé, ou réindexer")
        manifest = {"questions_sha256": truth["questions_sha256"], "index_doc_ids_sha256": index_sha,
                    "analysis_profile": search_config.analysis_profile.name,
                    "search_config_sha256": config_sha256(yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))),
                    "settings_sha256": settings_sha256()}
        data = _manifest_file(SEARCHES) or {"manifest": manifest, "records": {}}
        check_manifest(SEARCHES, manifest, data["manifest"])
        todo = [q for q in questions if q["id"] not in data["records"]]
        print(f"{len(data['records'])} recherche(s) faite(s), {len(todo)} à faire")
        for q in todo:
            try:
                result = searcher.search(q["question"])
            except (BudgetExceededError, LlmPermanentError) as exc:
                raise _stop(exc) from None
            if not result.trace.analysis.available:
                raise SystemExit(f"{q['id']} : analyse indisponible (quota ou erreur) — relancer plus tard")
            data["records"][q["id"]] = search_record(q, result, profile=generation.profile,
                                                     max_tokens=generation.max_tokens)
            _write_json_atomic(SEARCHES, data)
            rec = data["records"][q["id"]]
            print(f"{q['id']} : {len(rec['doc_ids'])} document(s), "
                  f"{'appel au LLM' if rec['llm_called'] else rec['fixed_status']}")
    called = sum(r["llm_called"] for r in data["records"].values())
    print(f"terminé : {called}/{len(data['records'])} questions appelleront le LLM ; dépensé {budget.spent:.4f} $")


def cmd_lancer(args) -> None:
    from RAG.src.evaluation.settings import load_settings, settings_sha256
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA
    from RAG.src.retrieval.retriever import Searcher, build_llm_client
    from RAG.src.utils.config import load_generation_config, load_search_config
    from RAG.src.utils.errors import LlmPermanentError

    settings = load_settings()
    if args.profil not in settings.candidates:
        raise SystemExit(f"profil {args.profil!r} hors des candidats {list(settings.candidates)}")
    if not 1 <= args.passage <= settings.passes:
        raise SystemExit(f"passage entre 1 et {settings.passes}")
    questions = {q["id"]: q for q in load_questions(QUESTIONS_PATH, settings.strata)}
    searches = _load_searches(list(questions.values()))
    llm_ids = sorted(i for i, r in searches["records"].items() if r["llm_called"])
    ids = llm_ids if args.passage == 1 else select_repeats(llm_ids, settings.repeat_questions, settings.seed_draw)
    profile = load_search_config().profiles[args.profil]
    generation = load_generation_config()
    out = OUT / "generations" / f"{args.profil}__p{args.passage}.json"
    manifest = {"questions_sha256": searches["manifest"]["questions_sha256"],
                "index_doc_ids_sha256": searches["manifest"]["index_doc_ids_sha256"],
                "analysis_profile": searches["manifest"]["analysis_profile"],
                "generation_prompt_sha": GENERATION_PROMPT_SHA, "profile": profile.name, "model": profile.model,
                "provider_tag": profile.provider_tag, "passage": args.passage,
                "generation_max_tokens": generation.max_tokens, "settings_sha256": settings_sha256()}
    data = _manifest_file(out) or {"manifest": manifest, "records": {}}
    check_manifest(out, manifest, data["manifest"])
    todo = [i for i in ids if i not in data["records"]]
    print(f"{args.profil} passage {args.passage} : {len(ids) - len(todo)} faite(s), {len(todo)} à faire")
    budget = Budget(SPENDING, settings.budget_usd, settings.reserve_per_call_usd)
    cached = CachedClient(BudgetedClient(build_llm_client(profile, None, generation.timeout_s), budget),
                          GENERATION_CACHE, f"generation-p{args.passage}")
    recorder = RecordingClient(cached)
    try:
        with Searcher(cache_path=ANALYSIS_CACHE, analysis_client=OfflineAnalysisClient()) as searcher:
            if searcher.index_doc_ids_sha256() != manifest["index_doc_ids_sha256"]:
                raise SystemExit("l'index a changé depuis `rechercher` : aucune génération lancée")
            for qid in todo:
                q = questions[qid]
                try:
                    record = generate_record(q, searches["records"][qid], searcher.search(q["question"]),
                                             recorder=recorder, cached=cached, profile=profile,
                                             max_tokens=generation.max_tokens, passage=args.passage)
                except (BudgetExceededError, LlmPermanentError) as exc:
                    raise _stop(exc) from None
                data["records"][qid] = record
                _write_json_atomic(out, data)
                print(f"{qid} : {record['status']} (modèle : {record['llm_status']})")
    finally:
        recorder.close()
    print(f"dépensé au total : {budget.spent:.4f} $ sur {settings.budget_usd} $")


def _judge_manifest(settings) -> dict:
    from RAG.src.evaluation.judge import JUDGE_PROMPT_SHA, JUDGE_PROMPT_VERSION
    return {"judge_prompt_version": JUDGE_PROMPT_VERSION, "judge_prompt_sha": JUDGE_PROMPT_SHA,
            "judge_model": settings.judge.model, "judge_provider_tag": settings.judge.provider_tag,
            "judge_max_tokens": settings.judge_max_tokens}


def cmd_juger(args) -> None:
    from RAG.src.evaluation.judge import JudgeOutputError, judge_answer
    from RAG.src.evaluation.settings import load_settings
    from RAG.src.llm.openrouter import OpenRouterClient
    from RAG.src.utils.config import load_openrouter_key
    from RAG.src.utils.errors import LlmPermanentError, LlmUnavailableError

    settings = load_settings()
    questions = {q["id"]: q for q in load_questions(QUESTIONS_PATH, settings.strata)}
    searches = _load_searches(list(questions.values()))["records"]
    generations = load_generations()
    if args.rejuger_echantillon:
        sample = _manifest_file(SAMPLE).get("cles")
        if not sample:
            raise SystemExit("échantillon absent : lancer `echantillonner`")
        by_key = {judge_key(p, pa, q): r for (p, pa), d in generations.items() for q, r in d["records"].items()}
        todo = [(k.replace("|r1", "|r2"), by_key[k]) for k in sample]
        repetition = 2
    else:
        todo = [(k, r) for k, r in answers_to_judge(generations)
                if args.profil is None or k.startswith(f"{args.profil}|")]
        repetition = 1
    manifest = _judge_manifest(settings)
    data = _manifest_file(JUDGEMENTS) or {"manifest": manifest, "records": {}}
    check_manifest(JUDGEMENTS, manifest, data["manifest"])
    todo = [(k, r) for k, r in todo if k not in data["records"]]
    print(f"{len(todo)} réponse(s) à juger (répétition {repetition})")
    budget = Budget(SPENDING, settings.budget_usd, settings.reserve_per_call_usd)
    client = CachedClient(BudgetedClient(OpenRouterClient(load_openrouter_key(), timeout_s=_JUDGE_TIMEOUT_S), budget),
                          JUDGE_CACHE, f"juge-r{repetition}")
    missing = 0
    try:
        for key, record in todo:
            _, _, qid, _ = parse_judge_key(key)
            try:
                judgement = judge_answer(client, settings.judge, question=questions[qid]["question"],
                                         context=searches[qid]["context"], answer=record["llm_text"],
                                         max_tokens=settings.judge_max_tokens)
            except (BudgetExceededError, LlmPermanentError) as exc:
                raise _stop(exc) from None
            except (JudgeOutputError, LlmUnavailableError) as exc:
                # Jamais un score : le jugement reste absent et sera retenté au prochain `juger`.
                # La sortie refusée quitte le cache (les appels précédents, valides, y restent).
                if isinstance(exc, JudgeOutputError):
                    client.forget_last()
                missing += 1
                print(f"{key} : jugement indisponible ({type(exc).__name__}), retenté au prochain passage")
                continue
            data["records"][key] = judgement.as_dict()
            _write_json_atomic(JUDGEMENTS, data)
            print(f"{key} : fidélité {judgement.faithfulness}, pertinence {judgement.relevance}")
    finally:
        client.close()
    print(f"terminé ; {missing} jugement(s) à retenter ; dépensé au total {budget.spent:.4f} $")


def cmd_echantillonner(args) -> None:
    from RAG.src.evaluation.settings import load_settings
    settings = load_settings()
    if SAMPLE.exists():
        raise SystemExit(f"{SAMPLE.name} existe déjà : l'échantillon est tiré une seule fois")
    generations = load_generations()
    judgements = _manifest_file(JUDGEMENTS).get("records", {})
    eligible, missing = [], []
    for (profile, passage), data in sorted(generations.items()):
        if passage != 1 or profile not in settings.candidates:
            continue
        for qid, record in sorted(data["records"].items()):
            if not judgeable(record):
                continue
            key = judge_key(profile, 1, qid)
            if key not in judgements:
                missing.append(key)
            elif judgements[key]["claims"]:
                eligible.append({"key": key, "profile": profile, "strate": record["strate"]})
    if missing:
        raise SystemExit(f"{len(missing)} réponse(s) du passage 1 non jugée(s) : terminer `juger`")
    keys = draw_sample(eligible, size=settings.sample_size, seed=settings.seed_draw, candidates=settings.candidates)
    _write_json_atomic(SAMPLE, {"cles": keys})
    print(f"échantillon : {len(keys)} réponses -> {SAMPLE} (fichier à ne pas ouvrir avant la fin de l'annotation)")


def cmd_annoter(args) -> None:
    from RAG.src.evaluation.settings import load_settings
    settings = load_settings()
    keys = _manifest_file(SAMPLE).get("cles")
    if not keys:
        raise SystemExit("échantillon absent : lancer `echantillonner`")
    questions = {q["id"]: q for q in load_questions(QUESTIONS_PATH, settings.strata)}
    searches = _load_searches(list(questions.values()))["records"]
    generations = load_generations()
    judgements = _manifest_file(JUDGEMENTS)["records"]
    items = []
    for n, key in enumerate(keys, start=1):
        profile, passage, qid, _ = parse_judge_key(key)
        items.append({"n": n, "question": questions[qid]["question"], "context": searches[qid]["context"],
                      "answer": generations[(profile, passage)]["records"][qid]["llm_text"],
                      "claims": judgements[key]["claims"]})
    done = _manifest_file(ANNOTATIONS)
    annotate(items, done, ask=input, show=print, save=lambda d: _write_json_atomic(ANNOTATIONS, d))
    print(f"{len(done)}/{len(items)} réponses annotées")


def cmd_evaluer(args) -> None:
    from dataclasses import asdict

    from RAG.src.evaluation.decision import choose
    from RAG.src.evaluation.settings import load_settings
    from RAG.src.utils.config import load_search_config

    settings = load_settings()
    questions = load_questions(QUESTIONS_PATH, settings.strata)
    searches_file = _load_searches(questions)
    searches = searches_file["records"]
    truth = _manifest_file(TRUTH)
    if truth.get("manifest", {}).get("questions_sha256") != searches_file["manifest"]["questions_sha256"]:
        raise SystemExit("vérité terrain et recherches portent sur deux jeux différents")
    relevant = truth["relevant"]
    generations = load_generations()
    judgements_file = _manifest_file(JUDGEMENTS)
    check_manifest(JUDGEMENTS, _judge_manifest(settings), judgements_file.get("manifest", {}))
    judgements = judgements_file["records"]
    llm_ids = sorted(i for i, r in searches.items() if r["llm_called"])
    repeat_ids = select_repeats(llm_ids, settings.repeat_questions, settings.seed_draw)
    problems = (manifest_problems(searches_file["manifest"], generations)
                + completeness_problems(settings.candidates, generations, judgements, llm_ids, repeat_ids,
                                        settings.passes))
    sample = _manifest_file(SAMPLE).get("cles") or []
    annotations = _manifest_file(ANNOTATIONS)
    if not sample or len(annotations) < len(sample):
        problems.append(f"annotation incomplète : {len(annotations)}/{len(sample) or settings.sample_size}")
    if problems:
        print("\n".join(problems[:30]))
        raise SystemExit(f"pas de conclusion : {len(problems)} problème(s) ci-dessus")

    strata = {q["id"]: q["strate"] for q in questions}
    retrieval = retrieval_metrics(searches, relevant, strata, load_search_config().k)
    results, details = [], {}
    for profile in settings.candidates:
        result, detail = candidate_result(profile, generations, judgements, searches, relevant, settings.passes)
        results.append(result)
        details[profile] = {**detail, "fidelite": result.mean_faithfulness, "pertinence": result.mean_relevance,
                            "taux_rejet": result.rejection_rate, "abstention_a_tort": result.wrong_abstention_rate,
                            "cout_moyen_usd": result.mean_cost,
                            "latence_mediane_ms": None if result.median_latency_ms == float("inf")
                            else result.median_latency_ms}
    agreement = agreement_report(sample, annotations, judgements, seed=settings.seed_bootstrap)
    kappa_f = agreement["fidelite"]["kappa"]
    kappa_r = agreement["pertinence"]["kappa_pondere"]
    t = settings.thresholds
    judge_valid = kappa_f is not None and kappa_f >= t.kappa_min
    relevance_valid = kappa_r is not None and kappa_r >= t.kappa_min
    decision = choose(results, t, use_relevance=relevance_valid, seed=settings.seed_bootstrap) if judge_valid else None
    report = {"recherche": retrieval, "candidats": details, "accord": agreement,
              "juge_valide": judge_valid, "pertinence_valide": relevance_valid,
              "decision": asdict(decision) if decision else None,
              "questions": {"total": len(questions), "llm_appele": len(llm_ids),
                            "message_fixe": len(questions) - len(llm_ids)},
              "fixe_par_statut": {s: sum(1 for r in searches.values() if r["fixed_status"] == s)
                                  for s in sorted({r["fixed_status"] for r in searches.values() if r["fixed_status"]})}}
    _write_json_atomic(EVALUATION, json.loads(json.dumps(report, allow_nan=False)))
    print(json.dumps({k: report[k] for k in ("recherche", "candidats", "accord")}, ensure_ascii=False, indent=1))
    if not judge_valid:
        print(f"\nkappa de fidélité {kappa_f} < {t.kappa_min} : scores du juge INDICATIFS, règle non appliquée. "
              "Décision à prendre sur la fidélité humaine ci-dessus (accord.fidelite_humaine).")
    else:
        if not relevance_valid:
            print(f"\nkappa de pertinence {kappa_r} < {t.kappa_min} : étape pertinence sautée.")
        print(f"\nmodèle retenu : {decision.chosen or 'aucun (tous éliminés)'} ; éliminés : {decision.eliminated}")
    print(f"rapport complet : {EVALUATION}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    tirer = sub.add_parser("tirer")
    tirer.add_argument("--sortie", help="chemin du brouillon (défaut : le fichier du jeu)")
    tirer.set_defaults(func=cmd_tirer)
    sub.add_parser("verite-terrain").set_defaults(func=cmd_verite_terrain)
    sub.add_parser("rechercher").set_defaults(func=cmd_rechercher)
    lancer = sub.add_parser("lancer")
    lancer.add_argument("--profil", required=True)
    lancer.add_argument("--passage", type=int, default=1, help="1 : jeu complet ; 2 et 3 : reprises")
    lancer.set_defaults(func=cmd_lancer)
    juger = sub.add_parser("juger")
    juger.add_argument("--profil", help="un seul candidat (défaut : tous)")
    juger.add_argument("--rejuger-echantillon", action="store_true",
                       help="rejuge l'échantillon hors cache (stabilité du juge, spec §7.3)")
    juger.set_defaults(func=cmd_juger)
    sub.add_parser("echantillonner").set_defaults(func=cmd_echantillonner)
    sub.add_parser("annoter").set_defaults(func=cmd_annoter)
    sub.add_parser("evaluer").set_defaults(func=cmd_evaluer)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
