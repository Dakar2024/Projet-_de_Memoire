"""Recette fonctionnelle de la génération (E2b, tâche 10).

  lancer   dans rag-search : pose chaque question (parties 1 à 4) au pipeline complet ;
           reprise possible (records.json écrit après CHAQUE question, cache de génération)
  evaluer  n'importe où : scores par partie, seuils, rejets listés ; refuse de conclure
           si des questions manquent

Les analyses viennent du cache de l'essai gratuit E2a (une seule fois payées en quota) ;
les générations sont mises en cache par `CachedGenerator`. Les latences rejouées depuis
un cache ne sont pas des mesures : le résumé les exclut (`from_cache`).
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
    real = [r["timings_ms"]["total"] for r in records if not r.get("from_cache")]
    summary["rejections"], summary["statuses"] = rejections, statuses
    summary["latency_ms"] = ({"median": float(np.percentile(real, 50)), "p95": float(np.percentile(real, 95)),
                              "n": len(real)} if real else {"median": None, "p95": None, "n": 0})
    summary["n_cached"] = len(records) - len(real)
    return summary


class CachedGenerator:
    """Enveloppe le client de génération d'un emplacement ; expose `complete_json` et `close`.

    Clé : sha256 de (GENERATION_PROMPT_SHA, modèle, provider_tag, message utilisateur exact).
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

    def _key(self, profile, user: str) -> str:
        payload = json.dumps([self._sha, profile.model, profile.provider_tag, user], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
        from RAG.src.llm.common import LlmCall
        key = self._key(profile, user)
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
    with QuestionPipeline(1, analysis_cache_path=ANALYSIS_CACHE) as pipeline:
        slot = pipeline.acquire()
        cached = CachedGenerator(slot.generator, OUT / "cache_generation.json", GENERATION_PROMPT_SHA)
        slot.generator = cached
        try:
            for q in todo:
                try:
                    result = pipeline.ask(slot, q["question"])
                except LlmQuotaExhaustedError:
                    print(QUOTA_MESSAGE, file=sys.stderr)
                    raise SystemExit(1) from None
                a = result.answer
                records.append({"id": q["id"], "part": q["part"], "status": a.status,
                                "scope_reason": a.scope_reason, "citations": [s.doc_id for s in a.sources],
                                "rejected": a.rejected, "answer": a.answer, "timings_ms": result.timings_ms,
                                "from_cache": cached.last_hit})
                _write_json_atomic(records_path, records)
                print(f"{q['id']} : {a.status}")
        finally:
            pipeline.release(slot)


def cmd_evaluer(args) -> None:
    questions = _load_questions()
    records = _load_records(OUT / "records.json")
    by_id = {r["id"]: r for r in records}
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
    n_ok, n_total = s["part2"]
    print("| Critère | Résultat | Seuil | Verdict |\n|---|---|---|---|")
    p3, p4 = s["part3"], s["part4"]
    print(f"| P2 (identifiants) | {n_ok}/{n_total} | 20/20 | {'OK' if n_ok == n_total == 20 else 'ÉCHEC'} |")
    print(f"| P3 (pièges) | {p3[0]}/{p3[1]} | 100 % | {'OK' if p3[0] == p3[1] else 'ÉCHEC'} |")
    print(f"| P4 (hors périmètre) | {p4[0]}/{p4[1]} | ≥ 9/10 | {'OK' if p4[0] >= 9 else 'ÉCHEC'} |")
    print(f"\nStatuts : {s['statuses']}")
    lat = s["latency_ms"]
    print(f"Latence (hors cache, n={lat['n']}) : médiane {lat['median']} ms, p95 {lat['p95']} ms ; "
          f"{s['n_cached']} rejeu(x) de cache exclus")
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
