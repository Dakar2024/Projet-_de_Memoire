"""Mesure de la recherche de E2a (spec E2a, §6.3).

Trois étapes, chacune avec son lieu d'exécution :
  verite-terrain  sur l'hôte (lit le Silver dans MinIO) : documents pertinents par question
  mesurer         dans rag-search : lance la recherche pour un profil et un mode
  evaluer         n'importe où : scores, critère d'acceptation, apport des ingrédients,
                  choix du modèle selon la règle fixée d'avance

Aucune conclusion si les manifestes divergent ou si une seule analyse a échoué.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import yaml

from RAG.experiments.comparaison_embeddings import bootstrap_mean_ci

QUESTIONS_PATH = Path(__file__).with_name("questions_recherche.yaml")
OUT = Path("data/experiments/e2a")
K = 10
SEED = 20261001
_ID_KEYS = ("rs", "hgvs_c", "hgvs_p", "genes")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))


# --- Fonctions pures, testées -----------------------------------------------------------

def score_question(question: dict, doc_ids: list[str], flags: list[str], identifiers: dict,
                   relevant: set[str], k: int = K) -> float:
    part = question["part"]
    if part == 1 and question["family"] == "A":
        for rank, doc_id in enumerate(doc_ids[:k], start=1):
            if doc_id in relevant:
                return 1.0 / rank
        return 0.0
    if part == 1:
        return sum(1 for doc_id in doc_ids[:k] if doc_id in relevant) / k
    if part == 2:
        return 1.0 if doc_ids and doc_ids[0] in relevant else 0.0
    expected = question["expected_identifiers"]
    same_ids = all(sorted(identifiers.get(key, [])) == sorted(expected.get(key, [])) for key in _ID_KEYS)
    return 1.0 if same_ids and set(question["expected_flags"]) <= set(flags) else 0.0


def choose_model(scores: dict[str, list[float]], costs: dict[str, float], seed: int = SEED) -> tuple[str, dict]:
    """Règle fixée avant la mesure : le meilleur score moyen désigne le meilleur modèle ;
    un modèle dont l'intervalle à 95 % de l'écart avec le meilleur contient zéro ne s'en
    distingue pas ; on retient le moins cher des modèles indistinguables du meilleur."""
    means = {name: float(np.mean(values)) for name, values in scores.items()}
    best = max(means, key=lambda name: (means[name], -costs[name]))
    intervals, indistinguishable = {}, [best]
    for name in scores:
        if name == best:
            continue
        diffs = np.array(scores[best]) - np.array(scores[name])
        mean, low, high = bootstrap_mean_ci(diffs, seed=seed)
        intervals[name] = {"ecart": mean, "ic_bas": low, "ic_haut": high}
        if low <= 0:
            indistinguishable.append(name)
    choice = min(indistinguishable, key=lambda name: costs[name])
    return choice, {"best": best, "means": means, "intervals": intervals,
                    "indistinguishable": sorted(indistinguishable), "costs": costs}


def significance_accuracy(questions: list[dict], analyses: dict[str, dict]) -> float:
    pairs = [(q["expected_significance"], analyses[q["id"]]["significance"]) for q in questions]
    return sum(expected == got for expected, got in pairs) / len(pairs)


# --- Sous-commandes --------------------------------------------------------------------

def cmd_verite_terrain(args) -> None:
    from RAG.experiments.comparaison_embeddings import _all_documents, _diseases_by_doc, _relevance

    questions = _load_questions()
    documents, diseases = _all_documents(), _diseases_by_doc()
    doc_ids = documents["doc_id"].to_list()
    relevant: dict[str, list[str]] = {}
    for q in questions:
        rule = q.get("relevant") or {}
        if q["part"] == 2:
            missing = set(rule["doc_ids"]) - set(doc_ids)
            if missing:
                raise SystemExit(f"{q['id']} : documents absents du Gold {sorted(missing)}")
            relevant[q["id"]] = list(rule["doc_ids"])
        elif q["part"] == 1:
            mask = _relevance(q, documents, diseases)
            relevant[q["id"]] = [doc_ids[i] for i in np.flatnonzero(mask)]
        else:
            relevant[q["id"]] = []
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"questions_sha256": _sha256(QUESTIONS_PATH),
                "gold_doc_ids_sha256": hashlib.sha256("\n".join(doc_ids).encode()).hexdigest()}
    (OUT / "verite_terrain.json").write_text(json.dumps({"manifest": manifest, "relevant": relevant}),
                                             encoding="utf-8")
    print(f"vérité terrain : {len(relevant)} questions")


def cmd_mesurer(args) -> None:
    from RAG.src.retrieval.retriever import Searcher

    questions = _load_questions()
    results, failures = {}, []
    with Searcher(profile_name=args.profile, cache_path=OUT / "cache_analyses.json") as searcher:
        profile = searcher.config.analysis_profile
        for q in questions:
            r = searcher.search(q["question"], mode=args.mode, force_exact=True if args.exact else None).as_dict()
            if not r["trace"]["analysis"]["available"]:
                failures.append(f"{q['id']} : {r['trace']['analysis']['error']}")
            results[q["id"]] = {"doc_ids": [d["doc_id"] for d in r["documents"]], "flags": r["trace"]["flags"],
                                "identifiers": r["trace"]["identifiers"], "analysis": r["trace"]["analysis"],
                                "timings_ms": r["trace"]["timings_ms"]}
    if failures:
        raise SystemExit("analyses indisponibles, mesure non enregistrée (relancer ; le cache garde les "
                         "réussites) :\n" + "\n".join(failures))
    from RAG.src.prompts.analysis import PROMPT_VERSION
    from RAG.src.utils.config import load_config
    manifest = {"questions_sha256": _sha256(QUESTIONS_PATH), "profile": profile.name, "model": profile.model,
                "provider_tag": profile.provider_tag, "prompt_version": PROMPT_VERSION, "mode": args.mode,
                "exact": bool(args.exact), "k": searcher.config.k,
                "embedding_fingerprint": load_config().embedding.fingerprint}
    name = f"{profile.name}__{args.mode}{'__exact' if args.exact else ''}.json"
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    (OUT / "runs" / name).write_text(json.dumps({"manifest": manifest, "results": results}, ensure_ascii=False),
                                     encoding="utf-8")
    print(f"{name} : {len(results)} questions")


def _load_run(path: Path, questions_sha: str, fingerprint: str | None) -> dict:
    run = json.loads(path.read_text(encoding="utf-8"))
    manifest = run["manifest"]
    if manifest["questions_sha256"] != questions_sha:
        raise SystemExit(f"{path.name} : questions modifiées depuis la mesure, remesurer")
    if fingerprint and manifest["embedding_fingerprint"] != fingerprint:
        raise SystemExit(f"{path.name} : modèle d'embedding différent des autres mesures")
    return run


def cmd_evaluer(args) -> None:
    questions = _load_questions()
    questions_sha = _sha256(QUESTIONS_PATH)
    truth = json.loads((OUT / "verite_terrain.json").read_text(encoding="utf-8"))
    if truth["manifest"]["questions_sha256"] != questions_sha:
        raise SystemExit("vérité terrain calculée sur d'autres questions : relancer verite-terrain")
    relevant = {qid: set(ids) for qid, ids in truth["relevant"].items()}
    runs = {p.stem: p for p in sorted((OUT / "runs").glob("*.json"))}
    fingerprint = None
    loaded = {}
    for name, path in runs.items():
        loaded[name] = _load_run(path, questions_sha, fingerprint)
        fingerprint = fingerprint or loaded[name]["manifest"]["embedding_fingerprint"]

    def scores_of(run: dict) -> dict[str, float]:
        return {q["id"]: score_question(q, run["results"][q["id"]]["doc_ids"], run["results"][q["id"]]["flags"],
                                        run["results"][q["id"]]["identifiers"], relevant[q["id"]], K)
                for q in questions}

    full = {n.split("__")[0]: r for n, r in loaded.items() if n.endswith("__full")}
    print("## Critère d'acceptation : partie 2 à 100 %\n")
    for profile, run in full.items():
        s = scores_of(run)
        part2 = [s[q["id"]] for q in questions if q["part"] == 2]
        print(f"- {profile} : {sum(part2):.0f}/{len(part2)} {'OK' if all(part2) else 'ÉCHEC — bug à corriger'}")

    costs = {p: sum(r["results"][q["id"]]["analysis"]["cost_usd"] for q in questions) for p, r in full.items()}
    per_q = {p: [scores_of(r)[q["id"]] for q in questions] for p, r in full.items()}
    choice, details = choose_model(per_q, costs)
    print("\n## Choix du modèle d'analyse (règle fixée d'avance)\n")
    print("| Profil | Score moyen | Coût total ($) | Exactitude signification |\n|---|---|---|---|")
    for p, run in full.items():
        analyses = {qid: res["analysis"] for qid, res in run["results"].items()}
        print(f"| {p} | {details['means'][p]:.3f} | {costs[p]:.4f} | {significance_accuracy(questions, analyses):.3f} |")
    for p, iv in details["intervals"].items():
        print(f"- {details['best']} − {p} : {iv['ecart']:+.3f}, IC 95 % [{iv['ic_bas']:+.3f}, {iv['ic_haut']:+.3f}]")
    print(f"\nDécision : **{choice}** (meilleur : {details['best']} ; indistinguables : {details['indistinguishable']})")

    print("\n## Apport de chaque ingrédient (profil retenu)\n")
    print("| Version | P1-A | P1-B | P1-C | P2 | P3 |\n|---|---|---|---|---|---|")
    for label, mode in (("V1 similarité", "similarity"), ("V2 + filtres", "filters"), ("V3 complète", "full")):
        run = loaded.get(f"{choice}__{mode}")
        if not run:
            print(f"| {label} | (mesure absente) |||||")
            continue
        s = scores_of(run)
        groups = [[s[q["id"]] for q in questions if q["part"] == 1 and q["family"] == fam] for fam in "ABC"]
        groups += [[s[q["id"]] for q in questions if q["part"] == part] for part in (2, 3)]
        print(f"| {label} | " + " | ".join(f"{np.mean(g):.3f}" for g in groups) + " |")

    exact_run = loaded.get(f"{choice}__similarity__exact")
    approx_run = loaded.get(f"{choice}__similarity")
    if exact_run and approx_run:
        overlaps = [len(set(exact_run["results"][q["id"]]["doc_ids"]) & set(approx_run["results"][q["id"]]["doc_ids"]))
                    / max(1, len(exact_run["results"][q["id"]]["doc_ids"])) for q in questions]
        print(f"\nDiagnostic : recouvrement moyen HNSW / exacte sans filtre = {np.mean(overlaps):.3f}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)
    sub.add_parser("verite-terrain").set_defaults(func=cmd_verite_terrain)
    p = sub.add_parser("mesurer")
    p.add_argument("--profile", required=True)
    p.add_argument("--mode", choices=("similarity", "filters", "full"), required=True)
    p.add_argument("--exact", action="store_true", help="force la recherche exacte (diagnostic HNSW)")
    p.set_defaults(func=cmd_mesurer)
    sub.add_parser("evaluer").set_defaults(func=cmd_evaluer)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
