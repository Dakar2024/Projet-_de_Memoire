"""Recette fonctionnelle de la génération (E2b, tâche 10).

  lancer   dans rag-search : pose chaque question (parties 1 à 4) au pipeline complet ;
           reprise possible (records.json écrit après CHAQUE question, cache de génération)
  evaluer  n'importe où : scores par partie, seuils, rejets listés ; refuse de conclure
           si des questions manquent

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
from pathlib import Path

import numpy as np
import yaml

_ROOT = Path(__file__).resolve().parents[2]  # racine du dépôt, ou /opt/projet dans le conteneur
EXPERIMENTS = Path(__file__).resolve().parent
QUESTIONS_E2A = EXPERIMENTS / "questions_recherche.yaml"
QUESTIONS_E2B = EXPERIMENTS / "questions_recette_e2b.yaml"
OUT = _ROOT / "data" / "experiments" / "e2b-recette"
ANALYSIS_CACHE = _ROOT / "data" / "experiments" / "e2a-essai" / "cache_analyses.json"
TRUTH_PATH = _ROOT / "data" / "experiments" / "e2a" / "verite_terrain.json"
ANALYSIS_MESSAGE = ("analyse indisponible (quota Groq épuisé ou erreur) — question non enregistrée ; "
                    "relancer après la réinitialisation, le cache garde les analyses et réponses obtenues")
QUOTA_MESSAGE = ("quota Groq épuisé — relancer après la réinitialisation ; "
                 "le cache garde les réponses obtenues")
_ANSWERED = {"answered", "partial"}
_NO_ANSWER = {"not_in_sources", "out_of_scope"}


def _write_json_atomic(path: Path, data) -> None:
    """Écriture atomique : un arrêt en cours d'écriture ne corrompt jamais le fichier."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# --- Fonctions pures, testées -----------------------------------------------------------

def score_recette(question: dict, record: dict, relevant: set[str]) -> dict:
    """Verdict d'une question selon sa partie ; `ok=None` en partie 1 (comptée, sans seuil)."""
    part, status, citations = question["part"], record["status"], record.get("citations") or []
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


def summarize(records: list[dict]) -> dict:
    """Comptes par partie (réussis, total), rejets par code, statuts, latences (médiane, p95)
    des seules questions réellement exécutées (hors rejeu du cache)."""
    summary: dict = {}
    for part in (2, 3, 4):
        scored = [r for r in records if r.get("part") == part]
        summary[f"part{part}"] = (sum(1 for r in scored if r.get("ok") is True), len(scored))
    rejections: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for r in records:
        if r.get("rejected"):
            rejections[r["rejected"]] = rejections.get(r["rejected"], 0) + 1
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    def real_total(r: dict) -> float:
        t = r["timings_ms"]
        # Analyse d'origine (même rejouée du cache) + embedding + base + génération en direct.
        return t["total"] - t.get("analysis", 0.0) + r.get("analysis_latency_ms", t.get("analysis", 0.0))

    def stats(values: list[float]) -> dict:
        return ({"median": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
                 "n": len(values)} if values else {"median": None, "p95": None, "n": 0})

    live = [r for r in records if not r.get("from_cache")]
    summary["rejections"], summary["statuses"] = rejections, statuses
    summary["latency_ms"] = stats([real_total(r) for r in live if r.get("generation_from_llm", True)])
    summary["latency_fixed_ms"] = stats([real_total(r) for r in live if not r.get("generation_from_llm", True)])
    summary["n_cached"] = len(records) - len(live)
    return summary


class CachedGenerator:
    """Enveloppe le client de génération d'un emplacement ; expose `complete_json` et `close`.

    Clé : sha256 de (GENERATION_PROMPT_SHA, modèle, provider_tag, max_tokens, message utilisateur exact).
    Le message utilisateur contient la question et le contexte échappé : il identifie
    exactement les documents transmis, sans avoir à en extraire les `doc_id`. Les appels
    échoués ne sont jamais mis en cache. `last_hit` dit si le dernier appel vient du cache.
    La latence de génération est mesurée hors du client : un rejeu est quasi instantané,
    d'où l'exclusion des rejeux dans `summarize`."""

    def __init__(self, inner, cache_path: Path, prompt_sha: str) -> None:
        self._inner, self._path, self._sha = inner, cache_path, prompt_sha
        self._cache: dict[str, dict] = (
            json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {})
        self.last_hit = False

    def _key(self, profile, user: str, max_tokens: int) -> str:
        payload = json.dumps([self._sha, profile.model, profile.provider_tag, max_tokens, user],
                             ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
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
        self._inner.close()


def build_record(question: dict, result, replayed: bool) -> dict:
    """Enregistrement d'une question. `replayed` : la génération a réellement été rejouée du cache."""
    a, analysis = result.answer, result.search.trace.analysis
    return {"id": question["id"], "part": question["part"], "status": a.status,
            "scope_reason": a.scope_reason, "citations": [s.doc_id for s in a.sources],
            "rejected": a.rejected, "answer": a.answer, "timings_ms": result.timings_ms,
            "from_cache": replayed, "generation_from_llm": a.from_llm,
            "analysis_available": analysis.available, "analysis_latency_ms": analysis.latency_ms,
            "analysis_from_cache": analysis.from_cache, "flags": list(result.search.trace.flags)}


# --- Commandes ----------------------------------------------------------------------------

def _load_questions() -> list[dict]:
    if not QUESTIONS_E2B.exists():
        raise SystemExit(f"fichier de questions hors périmètre absent : {QUESTIONS_E2B.name} "
                         "(partie 4, à faire valider par l'utilisateur avant la recette)")
    e2a = yaml.safe_load(QUESTIONS_E2A.read_text(encoding="utf-8"))
    e2b = yaml.safe_load(QUESTIONS_E2B.read_text(encoding="utf-8"))
    return list(e2a) + list(e2b)


def _load_records(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def cmd_lancer(args) -> None:
    from RAG.src.generation.pipeline import QuestionPipeline
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA
    from RAG.src.utils.errors import LlmQuotaExhaustedError

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
        cached = CachedGenerator(slot.generator, OUT / "cache_generation.json", GENERATION_PROMPT_SHA)
        slot.generator = cached
        try:
            for q in todo:
                cached.last_hit = False  # sinon une réponse à message fixe passerait pour un rejeu
                try:
                    result = pipeline.ask(slot, q["question"])
                except LlmQuotaExhaustedError:
                    print(QUOTA_MESSAGE, file=sys.stderr)
                    raise SystemExit(1) from None
                if not result.search.trace.analysis.available:
                    # Analyse dégradée : l'enregistrer fausserait recherche et réponse.
                    print(ANALYSIS_MESSAGE, file=sys.stderr)
                    raise SystemExit(1)
                a = result.answer
                records.append(build_record(q, result, cached.last_hit))
                _write_json_atomic(records_path, records)
                print(f"{q['id']} : {a.status}")
        finally:
            pipeline.release(slot)


def cmd_evaluer(args) -> None:
    questions = _load_questions()
    records = _load_records(OUT / "records.json")
    by_id = {r["id"]: r for r in records}
    known = {q["id"] for q in questions}
    for stray in sorted(set(by_id) - known):
        print(f"AVERTISSEMENT : enregistrement {stray} absent des fichiers de questions (ignoré)", file=sys.stderr)
    degraded = sorted(r["id"] for r in records if r.get("analysis_available") is False)
    if degraded:
        raise SystemExit(f"analyse indisponible pour {', '.join(degraded)} : enregistrements invalides, "
                         "supprimer ces questions de records.json et relancer")
    missing = [q["id"] for q in questions if q["id"] not in by_id]
    if missing:
        raise SystemExit(f"{len(missing)} question(s) sans enregistrement : {', '.join(missing)} — "
                         "aucune conclusion tant que la série n'est pas complète")
    relevant = {k: set(v) for k, v in json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["relevant"].items()}
    scored = []
    for q in questions:
        record = by_id[q["id"]]
        scored.append({**record, **score_recette(q, record, relevant.get(q["id"], set()))})
    s = summarize(scored)
    p2, p3, p4 = s["part2"], s["part3"], s["part4"]
    print("| Critère | Résultat | Seuil | Verdict |\n|---|---|---|---|")
    print(f"| P2 (identifiants) | {p2[0]}/{p2[1]} | tout | {'OK' if p2[0] == p2[1] else 'ÉCHEC'} |")
    print(f"| P3 (pièges) | {p3[0]}/{p3[1]} | tout | {'OK' if p3[0] == p3[1] else 'ÉCHEC'} |")
    print(f"| P4 (hors périmètre) | {p4[0]}/{p4[1]} | ≥ 90 % | {'OK' if p4[0] >= 0.9 * p4[1] else 'ÉCHEC'} |")
    print(f"\nStatuts : {s['statuses']}")
    for label, key in (("générées par le LLM", "latency_ms"), ("à message fixe", "latency_fixed_ms")):
        lat = s[key]
        print(f"Latence de bout en bout, réponses {label} (n={lat['n']}) : médiane {lat['median']} ms, "
              f"p95 {lat['p95']} ms")
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("lancer").set_defaults(func=cmd_lancer)
    sub.add_parser("evaluer").set_defaults(func=cmd_evaluer)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
