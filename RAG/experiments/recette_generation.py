"""Recette fonctionnelle de la génération (E2b, tâche 10).

  lancer   dans rag-search : pose chaque question (parties 1 à 4) au pipeline complet ;
           reprise possible (records.json écrit après CHAQUE question, cache de génération)
  rejouer  dans rag-search, SANS appel réseau au LLM : refait la recherche locale (analyses
           lues dans leur cache), repasse chaque génération en cache dans la chaîne de
           contrôles ACTUELLE et écrit records_v2.json
  diagnostiquer  comme `rejouer` (hors ligne, aucun appel au LLM) : pour chaque réponse
           `unverifiable` (ou `not_in_sources` au texte retenu et rejeté), explique QUEL identifiant,
           gène, terme de signification ou négation a déclenché le contrôle ; écrit
           diagnostic_rejets.json
  evaluer  n'importe où : scores par partie, seuils, rejets listés ; refuse de conclure
           si des questions manquent (`--fichier records_v2.json` pour le rejeu)

Deux séries hors périmètre (partie 4) : la série de développement
(`questions_recette_e2b.yaml`), qui a servi à écrire les règles de
RAG/src/generation/scope.py, et la série de contrôle (`questions_recette_e2b_controle.yaml`),
jamais consultée pour les écrire. Le seuil de la partie 4 se calcule sur la seule série de
contrôle ; la série de développement est rapportée à part.

Les analyses viennent du cache de l'essai gratuit E2a (une seule fois payées en quota) ;
les générations sont mises en cache par `CachedGenerator`. Les générations rejouées depuis
un cache ne sont pas des mesures : le résumé les exclut (`from_cache`). La latence de bout
en bout reconstitue l'analyse d'origine (`analysis_latency_ms`), même rejouée du cache.
Les latences sont celles du profil d'essai Groq, pas du profil de production OpenRouter.

Partie 3 : un piège sans indicateur attendu (`expected_flags` vide) interdit seulement le
statut `unverifiable` ; il ne vérifie pas que la réponse soit juste (examen manuel).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import yaml

_ROOT = Path(__file__).resolve().parents[2]  # racine du dépôt, ou /opt/projet dans le conteneur
EXPERIMENTS = Path(__file__).resolve().parent
QUESTIONS_E2A = EXPERIMENTS / "questions_recherche.yaml"
QUESTIONS_E2B = EXPERIMENTS / "questions_recette_e2b.yaml"
QUESTIONS_CONTROL = EXPERIMENTS / "questions_recette_e2b_controle.yaml"
DEVELOPMENT_SET, CONTROL_SET = "developpement", "controle"
OUT = _ROOT / "data" / "experiments" / "e2b-recette"
ANALYSIS_CACHE = _ROOT / "data" / "experiments" / "e2a-essai" / "cache_analyses.json"
TRUTH_PATH = _ROOT / "data" / "experiments" / "e2a" / "verite_terrain.json"
ANALYSIS_MESSAGE = ("analyse indisponible (quota Groq épuisé ou erreur) — question non enregistrée ; "
                    "relancer après la réinitialisation, le cache garde les analyses et réponses obtenues")
QUOTA_MESSAGE = ("quota Groq épuisé — relancer après la réinitialisation ; "
                 "le cache garde les réponses obtenues")
UNAVAILABLE_STATUS = "generation_unavailable"
_ANSWERED = {"answered", "partial"}
_NO_ANSWER = {"not_in_sources", "out_of_scope"}


def _write_json_atomic(path: Path, data) -> None:
    """Écrit un JSON de façon atomique (fichier temporaire, fsync, os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --- Fonctions pures, testées -----------------------------------------------------------

def score_recette(question: dict, record: dict, relevant: set[str]) -> dict:
    """Verdict d'une question selon sa partie ; `ok=None` en partie 1 (comptée, sans seuil)."""
    part, status, citations = question["part"], record["status"], record.get("citations") or []
    if part in (2, 3, 4) and status == UNAVAILABLE_STATUS:
        return {"ok": False}  # aucune réponse produite : le critère n'est pas rempli
    if part == 1:
        ok = None
    elif part == 2:
        ok = status in _ANSWERED and any(c in relevant for c in citations)
    elif part == 3:
        flags = set(question.get("expected_flags") or [])
        if flags & {"identifier_not_found", "gene_out_of_panel"}:
            ok = status in _NO_ANSWER and not citations
        else:
            ok = status != "unverifiable"
    elif part == 4:
        ok = status == "out_of_scope" and record.get("scope_reason") == question.get("expected_scope_reason")
    else:
        raise ValueError(f"partie inconnue : {part}")
    return {"ok": ok}


def _passed(scored: list[dict]) -> tuple[int, int]:
    """Compte les questions réussies et le total."""
    return sum(1 for r in scored if r.get("ok") is True), len(scored)


def real_total(r: dict, *, with_waits: bool = False) -> float:
    """Calcule la latence de bout en bout, hors attentes de limite de débit sauf demande."""
    t = r["timings_ms"]
    total = t["total"] - t.get("analysis", 0.0) + r.get("analysis_latency_ms", t.get("analysis", 0.0))
    return total if with_waits else total - r.get("throttle_wait_ms", 0.0)


def summarize(records: list[dict]) -> dict:
    """Résume la recette : réussites par partie, rejets, statuts et latences des questions exécutées."""
    summary: dict = {}
    for part in (2, 3):
        summary[f"part{part}"] = _passed([r for r in records if r.get("part") == part])
    part4 = [r for r in records if r.get("part") == 4]
    summary["part4"] = _passed([r for r in part4 if r.get("set") == CONTROL_SET])
    summary["part4_dev"] = _passed([r for r in part4 if r.get("set") != CONTROL_SET])
    summary["part2_partial"] = sum(1 for r in records if r.get("part") == 2 and r.get("ok") is True
                                   and r.get("status") == "partial")
    rejections: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for r in records:
        if r.get("rejected"):
            rejections[r["rejected"]] = rejections.get(r["rejected"], 0) + 1
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    def stats(values: list[float]) -> dict:
        """Calcule médiane et p95."""
        return ({"median": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
                 "n": len(values)} if values else {"median": None, "p95": None, "n": 0})

    # Une génération indisponible n'a pas de latence de bout en bout : hors des statistiques.
    live = [r for r in records if not r.get("from_cache") and r["status"] != UNAVAILABLE_STATUS]
    summary["rejections"], summary["statuses"] = rejections, statuses
    by_llm = [r for r in live if r.get("generation_from_llm", True)]
    summary["latency_ms"] = stats([real_total(r) for r in by_llm])
    summary["latency_with_waits_ms"] = stats([real_total(r, with_waits=True) for r in by_llm])
    summary["latency_fixed_ms"] = stats([real_total(r) for r in live if not r.get("generation_from_llm", True)])
    summary["n_upper_bound"] = sum(1 for r in live if "throttle_wait_ms" not in r)
    summary["n_cached"] = sum(1 for r in records if r.get("from_cache"))
    return summary


class ThrottleMeter:
    """Mesure les attentes des clients LLM (limite de débit, relances), hors latence du pipeline."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self.total_s = 0.0

    def wrap(self, sleep: Callable[[float], None]) -> Callable[[float], None]:
        """Enveloppe une fonction `sleep` pour en compter la durée."""
        def measured(seconds: float) -> None:
            """Attend en comptant la durée."""
            start = self._clock()
            try:
                sleep(seconds)
            finally:
                self.total_s += self._clock() - start
        return measured

    def install(self, client) -> bool:
        """Enveloppe `client._sleep` s'il existe (GroqClient, OpenRouterClient)."""
        if client is None or not callable(getattr(client, "_sleep", None)):
            return False
        client._sleep = self.wrap(client._sleep)
        return True

    def reset(self) -> None:
        """Remet le compteur à zéro."""
        self.total_s = 0.0

    @property
    def total_ms(self) -> float:
        """Renvoie le total des attentes en millisecondes."""
        return self.total_s * 1000


def cache_key(prompt_sha: str, profile, user: str, max_tokens: int) -> str:
    """Clé du cache de génération, partagée par `CachedGenerator` et le rejeu."""
    payload = json.dumps([prompt_sha, profile.model, profile.provider_tag, max_tokens, user], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedGenerator:
    """Cache disque des générations réussies, par prompt, modèle, point d'accès, plafond et message exact."""

    def __init__(self, inner, cache_path: Path, prompt_sha: str) -> None:
        self._inner, self._path, self._sha = inner, cache_path, prompt_sha
        self._cache: dict[str, dict] = (
            json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {})
        self.last_hit = False

    def _key(self, profile, user: str, max_tokens: int) -> str:
        """Calcule la clé de cache d'une génération."""
        return cache_key(self._sha, profile, user, max_tokens)

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
        """Renvoie la génération en cache, sinon appelle le client et la met en cache."""
        from RAG.src.llm.common import LlmCall
        key = self._key(profile, user, max_tokens)
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
        """Ferme le client enveloppé."""
        self._inner.close()


def build_unavailable_record(question: dict, error: Exception) -> dict:
    """Enregistre une génération indisponible (classe d'erreur seulement, jamais son texte)."""
    from RAG.src.prompts.generation import GENERATION_PROMPT_VERSION
    return {"id": question["id"], "part": question["part"], "status": UNAVAILABLE_STATUS,
            "error": type(error).__name__, "scope_reason": None, "citations": [], "rejected": None,
            "answer": "", "from_cache": False, "prompt_version": GENERATION_PROMPT_VERSION}


def build_record(question: dict, result, replayed: bool) -> dict:
    """Construit l'enregistrement d'une question, texte retenu d'un `not_in_sources` compris."""
    from RAG.src.prompts.generation import GENERATION_PROMPT_VERSION
    a, analysis = result.answer, result.search.trace.analysis
    doc_ids = [s.doc_id for s in a.sources]
    record = {"id": question["id"], "part": question["part"], "status": a.status,
              "prompt_version": GENERATION_PROMPT_VERSION,
              "scope_reason": a.scope_reason, "citations": [] if a.status == "unverifiable" else doc_ids,
              "rejected": a.rejected, "answer": a.answer, "timings_ms": result.timings_ms,
              "from_cache": replayed, "generation_from_llm": a.from_llm,
              "analysis_available": analysis.available, "analysis_latency_ms": analysis.latency_ms,
              "analysis_from_cache": analysis.from_cache, "flags": list(result.search.trace.flags)}
    if a.status == "unverifiable":
        record["sources_transmises"] = doc_ids
    withheld = getattr(a, "llm_text_withheld", None)
    if withheld is not None:
        record["llm_text_withheld"] = withheld
    return record


# --- Commandes ----------------------------------------------------------------------------

def _load_questions() -> list[dict]:
    """Charge les questions des parties 1 à 4, chacune avec sa série."""
    for path, label in ((QUESTIONS_E2B, "hors périmètre"), (QUESTIONS_CONTROL, "de la série de contrôle")):
        if not path.exists():
            raise SystemExit(f"fichier de questions {label} absent : {path.name} "
                             "(partie 4, à faire valider par l'utilisateur avant la recette)")
    e2a = list(yaml.safe_load(QUESTIONS_E2A.read_text(encoding="utf-8")) or [])
    development = [{**q, "set": DEVELOPMENT_SET}
                   for q in yaml.safe_load(QUESTIONS_E2B.read_text(encoding="utf-8")) or []]
    control = []
    for q in yaml.safe_load(QUESTIONS_CONTROL.read_text(encoding="utf-8")) or []:
        if q.get("set", CONTROL_SET) != CONTROL_SET:
            raise SystemExit(f"{q.get('id')} : série « {q.get('set')} » dans le fichier de contrôle")
        control.append({**q, "set": CONTROL_SET})
    questions = e2a + development + control
    ids = [q["id"] for q in questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SystemExit(f"identifiants de questions en double : {', '.join(duplicates)}")
    return questions


def _load_records(path: Path) -> list[dict]:
    """Charge les enregistrements existants."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def cmd_lancer(args) -> None:
    """Pose chaque question au pipeline complet, avec reprise après chaque question."""
    from RAG.src.generation.pipeline import QuestionPipeline
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA
    from RAG.src.utils.errors import LlmQuotaExhaustedError, LlmUnavailableError

    questions = _load_questions()
    records_path = OUT / "records.json"
    records = _load_records(records_path)
    done = {r["id"] for r in records}
    todo = [q for q in questions if q["id"] not in done]
    print(f"{len(done)} question(s) déjà enregistrée(s), {len(todo)} à poser")
    truth_manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["manifest"]
    with QuestionPipeline(1, analysis_cache_path=ANALYSIS_CACHE) as pipeline:
        slot = pipeline.acquire()
        if slot.searcher.index_doc_ids_sha256() != truth_manifest["gold_doc_ids_sha256"]:
            pipeline.release(slot)
            raise SystemExit("l'index ne contient pas les documents de la vérité terrain E2a : "
                             "relancer verite-terrain sur le Gold indexé, ou réindexer")
        # Attentes des clients (limite de débit) mesurées par question, avant l'enveloppe de cache.
        meter = ThrottleMeter()
        meter.install(slot.generator)
        meter.install(getattr(slot.searcher, "_llm", None))
        cached = CachedGenerator(slot.generator, OUT / "cache_generation.json", GENERATION_PROMPT_SHA)
        slot.generator = cached
        try:
            for q in todo:
                cached.last_hit = False  # sinon une réponse à message fixe passerait pour un rejeu
                meter.reset()
                try:
                    result = pipeline.ask(slot, q["question"])
                except LlmQuotaExhaustedError:
                    print(QUOTA_MESSAGE, file=sys.stderr)
                    raise SystemExit(1) from None
                except LlmUnavailableError as exc:
                    # Génération indisponible (sortie hors schéma, 5xx...) : consignée, la recette continue.
                    records.append({**build_unavailable_record(q, exc), "throttle_wait_ms": meter.total_ms})
                    _write_json_atomic(records_path, records)
                    print(f"{q['id']} : {UNAVAILABLE_STATUS} ({type(exc).__name__})")
                    continue
                if not result.search.trace.analysis.available:
                    # Analyse dégradée : l'enregistrer fausserait recherche et réponse.
                    print(ANALYSIS_MESSAGE, file=sys.stderr)
                    raise SystemExit(1)
                a = result.answer
                records.append({**build_record(q, result, cached.last_hit), "throttle_wait_ms": meter.total_ms})
                _write_json_atomic(records_path, records)
                print(f"{q['id']} : {a.status}")
        finally:
            pipeline.release(slot)


def _records_path(name: str | None) -> Path:
    """Renvoie le chemin d'un fichier d'enregistrements."""
    path = Path(name or "records.json")
    return path if path.is_absolute() else OUT / path


def cmd_evaluer(args) -> None:
    """Calcule et affiche le bilan de la recette."""
    questions = _load_questions()
    records = _load_records(_records_path(getattr(args, "fichier", None)))
    by_id = {r["id"]: r for r in records}
    known = {q["id"] for q in questions}
    for stray in sorted(set(by_id) - known):
        print(f"AVERTISSEMENT : enregistrement {stray} absent des fichiers de questions (ignoré)", file=sys.stderr)
    degraded = sorted(r["id"] for r in records if r.get("analysis_available") is False)
    if degraded:
        raise SystemExit(f"analyse indisponible pour {', '.join(degraded)} : enregistrements invalides, "
                         "supprimer ces questions de records.json et relancer")
    versions = sorted({str(r.get("prompt_version")) for r in records})
    if len(versions) > 1:
        raise SystemExit(f"enregistrements de plusieurs versions du prompt ({', '.join(versions)}) : "
                         "supprimer data/experiments/e2b-recette et relancer")
    missing = [q["id"] for q in questions if q["id"] not in by_id]
    if missing:
        raise SystemExit(f"{len(missing)} question(s) sans enregistrement : {', '.join(missing)} — "
                         "aucune conclusion tant que la série n'est pas complète")
    relevant = {k: set(v) for k, v in json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["relevant"].items()}
    scored = []
    for q in questions:
        record = by_id[q["id"]]
        scored.append({**record, **score_recette(q, record, relevant.get(q["id"], set())), "set": q.get("set")})
    s = summarize(scored)
    p2, p3, p4, p4_dev = s["part2"], s["part3"], s["part4"], s["part4_dev"]
    p4_ok = p4[1] > 0 and p4[0] >= 0.9 * p4[1]
    print("| Critère | Résultat | Seuil | Verdict |\n|---|---|---|---|")
    print(f"| P2 (identifiants) | {p2[0]}/{p2[1]} | tout | {'OK' if p2[0] == p2[1] else 'ÉCHEC'} |")
    print(f"| P3 (pièges) | {p3[0]}/{p3[1]} | tout | {'OK' if p3[0] == p3[1] else 'ÉCHEC'} |")
    print(f"| P4 (hors périmètre, série de contrôle) | {p4[0]}/{p4[1]} | ≥ 90 % | {'OK' if p4_ok else 'ÉCHEC'} |")
    print(f"| P4, série de développement (ayant servi à écrire les règles) | {p4_dev[0]}/{p4_dev[1]} "
          "| sans seuil | indicatif |")
    if s["part2_partial"]:
        print(f"\nP2 : {s['part2_partial']} réponse(s) « partial » acceptée(s) comme réussies.")
    print(f"\nStatuts : {s['statuses']}")
    for label, key in (("générées par le LLM, sans les attentes de limite de débit", "latency_ms"),
                       ("générées par le LLM, attentes comprises", "latency_with_waits_ms"),
                       ("à message fixe, sans les attentes", "latency_fixed_ms")):
        lat = s[key]
        print(f"Latence de bout en bout, réponses {label} (n={lat['n']}) : médiane {lat['median']} ms, "
              f"p95 {lat['p95']} ms")
    if s["n_upper_bound"]:
        print(f"{s['n_upper_bound']} enregistrement(s) antérieur(s) sans mesure des attentes "
              "(throttle_wait_ms) : leur latence « sans attentes » est une borne supérieure.")
    print(f"{s['n_cached']} rejeu(x) de génération exclus. Latences mesurées avec le profil d'essai "
          "Groq, pas avec le profil de production OpenRouter.")
    print("\nRéponses rejetées :")
    rejected = [r for r in scored if r.get("rejected")]
    for r in rejected:
        print(f"- {r['id']} : {r['rejected']}")
    if not rejected:
        print("- aucune")
    failed = [r["id"] for r in scored if r.get("ok") is False]
    print(f"\nQuestions en échec : {', '.join(failed) if failed else 'aucune'}")


class GenerationNotCached(Exception):
    """Rejeu : génération absente du cache (jamais obtenue, ou documents différents)."""


class ReplayClient:
    """Client de rejeu : sert les générations du cache, sans réseau."""

    def __init__(self, cache: dict, prompt_sha: str) -> None:
        self._cache, self._sha = cache, prompt_sha
        self.calls = 0

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
        """Renvoie la génération en cache, ou lève `GenerationNotCached`."""
        from RAG.src.llm.common import LlmCall
        key = cache_key(self._sha, profile, user, max_tokens)
        if key not in self._cache:
            raise GenerationNotCached(key)
        self.calls += 1
        return LlmCall(**self._cache[key])

    def close(self) -> None:
        """Ne fait rien (aucune session)."""


class OfflineAnalysisClient:
    """Client d'analyse hors ligne : toute analyse absente du cache est indisponible, sans appel."""

    def complete_json(self, *args, **kwargs):
        """Lève toujours : l'analyse doit venir du cache."""
        from RAG.src.utils.errors import LlmUnavailableError
        raise LlmUnavailableError("rejeu hors ligne : analyse absente du cache")

    def close(self) -> None:
        """Ne fait rien (aucune session)."""


def replay_records(questions: list[dict], v1_records: list[dict], *, search, generate) -> list[dict]:
    """Repasse chaque question enregistrée dans la chaîne actuelle, générations rejouées du cache."""
    from RAG.src.generation.pipeline import PipelineResult
    from RAG.src.utils.errors import LlmUnavailableError
    by_id = {r["id"]: r for r in v1_records}
    out: list[dict] = []
    for q in questions:
        v1 = by_id.get(q["id"])
        if v1 is None:
            continue
        kept = {**v1, "v1_status": v1["status"]}
        result = search(q["question"])
        if not result.trace.analysis.available:
            out.append({**kept, "replay": "analysis_not_cached"})
            continue
        try:
            answer = generate(q["question"], result)
        except GenerationNotCached:
            out.append({**kept, "replay": "generation_not_cached"})
            continue
        except LlmUnavailableError as exc:
            out.append({**build_unavailable_record(q, exc), "v1_status": v1["status"], "replay": "replayed"})
            continue
        record = build_record(q, PipelineResult(answer=answer, search=result, timings_ms=v1.get("timings_ms", {})),
                              replayed=True)
        for field in ("analysis_latency_ms", "throttle_wait_ms"):
            if field in v1:
                record[field] = v1[field]
        out.append({**record, "v1_status": v1["status"], "replay": "replayed"})
    return out


class RecordingReplayClient(ReplayClient):
    """Client de rejeu qui garde le contenu de la dernière génération."""

    last_content = None

    def complete_json(self, *args, **kwargs):
        """Renvoie la génération en cache et la garde."""
        call = super().complete_json(*args, **kwargs)
        self.last_content = call.content
        return call


def diagnose_records(questions: list[dict], v1_records: list[dict], *, search, generate, client) -> list[dict]:
    """Explique chaque réponse rejetée en rejouant les contrôles sur le texte du LLM."""
    from RAG.src.generation.answer import validate_generation
    from RAG.src.generation.checks import explain_rejection, strip_cited_labels
    from RAG.src.generation.context import resolve_citations
    from RAG.src.utils.errors import LlmUnavailableError
    by_id = {r["id"]: r for r in v1_records}
    out: list[dict] = []
    for q in questions:
        if q["id"] not in by_id:
            continue
        result = search(q["question"])
        if not result.trace.analysis.available:
            continue
        client.last_content = None
        try:
            answer = generate(q["question"], result)
        except (GenerationNotCached, LlmUnavailableError):
            continue
        rejected_text = answer.status == "unverifiable" or (answer.status == "not_in_sources" and answer.rejected)
        if not rejected_text or client.last_content is None:
            continue
        status, _reason, text, citations = validate_generation(client.last_content)
        if status in ("answered", "partial"):
            text = strip_cited_labels(text, citations)  # même préparation que generate_answer
        explanation = explain_rejection(text, result.documents,
                                        resolve_citations(citations, result.documents), status, q["question"])
        out.append({"id": q["id"], "answer_status": answer.status, "llm_status": status,
                    "reason": explanation["reason"] if explanation else answer.rejected,
                    "detail": explanation["detail"] if explanation else [],
                    "citations": citations, "excerpt": text[:200]})
    return out


def _status_counts(records: list[dict]) -> dict[str, int]:
    """Compte les enregistrements par statut."""
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return dict(sorted(counts.items()))


def cmd_rejouer(args) -> None:
    """Rejoue la recette hors ligne et écrit records_v2.json."""
    from RAG.src.generation.answer import generate_answer
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA
    from RAG.src.retrieval.retriever import Searcher
    from RAG.src.utils.config import load_generation_config

    questions = _load_questions()
    v1 = _load_records(OUT / "records.json")
    cache_path = OUT / "cache_generation.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    g = load_generation_config()
    client = ReplayClient(cache, GENERATION_PROMPT_SHA)
    truth_manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["manifest"]
    # Aucun client LLM construit : analyses lues dans leur cache, générations dans le leur.
    with Searcher(cache_path=ANALYSIS_CACHE, analysis_client=OfflineAnalysisClient()) as searcher:
        if searcher.index_doc_ids_sha256() != truth_manifest["gold_doc_ids_sha256"]:
            raise SystemExit("l'index ne contient pas les documents de la vérité terrain E2a : rejeu impossible")
        v2 = replay_records(questions, v1, search=searcher.search,
                            generate=lambda q, r: generate_answer(q, r, client=client, profile=g.profile,
                                                                  max_tokens=g.max_tokens))
    _write_json_atomic(OUT / "records_v2.json", v2)
    replay: dict[str, int] = {}
    for r in v2:
        replay[r["replay"]] = replay.get(r["replay"], 0) + 1
    print(f"{len(v2)} enregistrement(s) rejoué(s) sur {len(v1)} ; issue du rejeu : {replay} ; "
          f"{client.calls} génération(s) relue(s) du cache")
    print(f"Statuts v1 : {_status_counts(v1)}")
    print(f"Statuts v2 : {_status_counts(v2)}")
    for r in v2:
        if r["status"] != r["v1_status"]:
            print(f"- {r['id']} : {r['v1_status']} -> {r['status']}"
                  + (f" ({r['scope_reason']})" if r.get("scope_reason") else "")
                  + (f" [{r['rejected']}]" if r.get("rejected") else ""))


def cmd_diagnostiquer(args) -> None:
    """Rejoue hors ligne et explique chaque rejet."""
    from RAG.src.generation.answer import generate_answer
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA
    from RAG.src.retrieval.retriever import Searcher
    from RAG.src.utils.config import load_generation_config

    questions = _load_questions()
    v1 = _load_records(OUT / "records.json")
    cache_path = OUT / "cache_generation.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    g = load_generation_config()
    client = RecordingReplayClient(cache, GENERATION_PROMPT_SHA)
    truth_manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["manifest"]
    with Searcher(cache_path=ANALYSIS_CACHE, analysis_client=OfflineAnalysisClient()) as searcher:
        if searcher.index_doc_ids_sha256() != truth_manifest["gold_doc_ids_sha256"]:
            raise SystemExit("l'index ne contient pas les documents de la vérité terrain E2a : diagnostic impossible")
        diagnostics = diagnose_records(
            questions, v1, search=searcher.search, client=client,
            generate=lambda q, r: generate_answer(q, r, client=client, profile=g.profile, max_tokens=g.max_tokens))
    _write_json_atomic(OUT / "diagnostic_rejets.json", diagnostics)
    by_reason: dict[str, int] = {}
    for d in diagnostics:
        by_reason[d["reason"]] = by_reason.get(d["reason"], 0) + 1
    print(f"{len(diagnostics)} réponse(s) rejetée(s) expliquée(s) : {by_reason}")
    for d in diagnostics:
        print(f"\n- {d['id']} [{d['answer_status']}] {d['reason']}")
        for item in d["detail"]:
            print(f"    déclencheur : {item}")
        print(f"    extrait : {d['excerpt']}")


def main(argv: list[str] | None = None) -> None:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("lancer").set_defaults(func=cmd_lancer)
    sub.add_parser("rejouer").set_defaults(func=cmd_rejouer)
    sub.add_parser("diagnostiquer").set_defaults(func=cmd_diagnostiquer)
    evaluer = sub.add_parser("evaluer")
    evaluer.add_argument("--fichier", default="records.json",
                         help="enregistrements à évaluer, relatifs à data/experiments/e2b-recette")
    evaluer.set_defaults(func=cmd_evaluer)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
