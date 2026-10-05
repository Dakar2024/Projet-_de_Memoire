"""Mesure de la recherche de E2a (spec E2a, §6.3).

Trois étapes, chacune avec son lieu d'exécution :
  verite-terrain  sur l'hôte (lit le Silver dans MinIO) : documents pertinents par question
  mesurer         dans rag-search : lance la recherche pour un profil et un mode
  evaluer         n'importe où : scores, critère d'acceptation, apport des ingrédients,
                  choix du modèle selon la règle fixée d'avance

Aucune conclusion si les manifestes divergent ou si une seule analyse a échoué.

Essai gratuit (profils de `llm.trial_profiles`, Groq) : `mesurer --profile <essai>` écrit
dans data/experiments/e2a-essai, jamais dans e2a ; `evaluer --essai` y lit ses séries et
affiche les mêmes contrôles et scores, sans choix de modèle. La vérité terrain reste celle
de e2a (lue seulement). `evaluer` sans `--essai` ignore les essais.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from RAG.experiments.comparaison_embeddings import bootstrap_mean_ci

QUESTIONS_PATH = Path(__file__).resolve().with_name("questions_recherche.yaml")
_ROOT = Path(__file__).resolve().parents[2]  # racine du dépôt, ou /opt/projet dans le conteneur
OUT = _ROOT / "data" / "experiments" / "e2a"
# Séries de l'essai gratuit : jamais mêlées aux séries officielles.
OUT_ESSAI = _ROOT / "data" / "experiments" / "e2a-essai"
E1_SCORES_PATH = _ROOT / "data" / "experiments" / "scores.json"
K = 10
SEED = 20261001
_ID_KEYS = ("rs", "hgvs_c", "hgvs_p", "genes")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))


# --- Fonctions pures, testées -----------------------------------------------------------

def score_question(question: dict, doc_ids: list[str], flags: list[str], identifiers: dict,
                   relevant: set[str], k: int = K, stages: list[str] | None = None) -> float:
    """Score d'une question. Partie 2 : le premier document doit être pertinent ET venir de
    la correspondance exacte (`stages[0] == "exact"` quand les étapes sont connues), sans
    `identifier_not_found` : un document trouvé par similarité ne compte pas."""
    part = question["part"]
    if part == 1 and question["family"] == "A":
        for rank, doc_id in enumerate(doc_ids[:k], start=1):
            if doc_id in relevant:
                return 1.0 / rank
        return 0.0
    if part == 1:
        return sum(1 for doc_id in doc_ids[:k] if doc_id in relevant) / k
    if part == 2:
        found_exactly = stages is None or (bool(stages) and stages[0] == "exact")
        return 1.0 if (doc_ids and doc_ids[0] in relevant and "identifier_not_found" not in flags
                       and found_exactly) else 0.0
    expected = question["expected_identifiers"]
    same_ids = all(sorted(identifiers.get(key, [])) == sorted(expected.get(key, [])) for key in _ID_KEYS)
    return 1.0 if same_ids and set(question["expected_flags"]) <= set(flags) else 0.0


def choose_model(scores: dict[str, list[float]], costs: dict[str, float], seed: int = SEED) -> tuple[str, dict]:
    """Règle fixée avant la mesure : le meilleur score moyen désigne le meilleur modèle ;
    un modèle dont l'intervalle à 95 % de l'écart avec le meilleur contient zéro ne s'en
    distingue pas ; on retient le moins cher des modèles indistinguables du meilleur."""
    if not scores:
        raise ValueError("choose_model : aucun modèle à comparer")
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


def exact_doc_ids(documents: pl.DataFrame, identifiers) -> set[str]:
    """Documents de variant que la correspondance exacte doit retrouver (même sémantique que
    PgSearchStore.exact_matches : rs OU HGVS c. OU HGVS p., restreint aux gènes cités ; si seul un
    gène hors panneau est cité, les HGVS sont ignorés et seul le rs compte)."""
    hgvs_searchable = not (identifiers.out_of_panel and not identifiers.genes)
    hgvs_c, hgvs_p = (identifiers.hgvs_c, identifiers.hgvs_p) if hgvs_searchable else ((), ())
    match = (pl.col("rs_dbsnp").is_in(list(identifiers.rs)) | pl.col("hgvs_c").is_in(list(hgvs_c))
             | pl.col("hgvs_p").is_in(list(hgvs_p)))
    selected = documents.filter((pl.col("doc_type") == "variant") & match)
    if identifiers.genes:
        selected = selected.filter(pl.col("gene_symbol").is_in(list(identifiers.genes)))
    return set(selected["doc_id"].to_list())


def v0_scores(e1_scores: dict, questions: list[dict]) -> dict[str, list[float]]:
    """Scores E1 (neuml) regroupés par famille de la partie 1 ; `A01` correspond à `P1-A01`."""
    neuml = e1_scores.get("neuml") if isinstance(e1_scores, dict) else None
    if not isinstance(neuml, dict):
        raise SystemExit("scores E1 sans le modèle « neuml » : fichier de E1 inattendu, V0 non calculable")
    groups: dict[str, list[float]] = {"A": [], "B": [], "C": []}
    for q in questions:
        if q["part"] != 1:
            continue
        key = q["id"].removeprefix("P1-")
        if key not in neuml:
            raise SystemExit(f"scores E1 : question {key} absente")
        groups[q["family"]].append(float(neuml[key]))
    return groups


def load_v0_scores(path: Path, questions: list[dict]) -> dict[str, list[float]] | None:
    """Scores V0 depuis le fichier de E1 ; `None` s'il est absent (la ligne V0 le signale)."""
    if not path.exists():
        return None
    return v0_scores(json.loads(path.read_text(encoding="utf-8")), questions)


def config_sha256(raw_config: dict) -> str:
    """Empreinte des sections `search` et `llm` de RAG/config.yaml, sans
    `llm.analysis_profile` : ce choix change à la mise en service, pas les conditions de mesure ;
    ni `llm.trial_profiles` : les séries officielles ne dépendent pas des essais."""
    llm = {key: value for key, value in (raw_config.get("llm") or {}).items()
           if key not in ("analysis_profile", "trial_profiles")}
    sections = {"search": raw_config.get("search"), "llm": llm}
    return hashlib.sha256(json.dumps(sections, sort_keys=True).encode("utf-8")).hexdigest()


def output_dir(config) -> Path:
    """Dossier des séries et du cache du profil d'analyse : e2a-essai pour un profil
    d'essai, e2a pour un profil officiel."""
    return OUT_ESSAI if config.analysis_profile.name in config.trial_profiles else OUT


def check_trial_field(run_profiles: set[str], trial_profiles: set[str]) -> None:
    """Les séries d'essai ne portent que sur des profils d'essai configurés : une série
    d'un profil officiel n'a rien à faire dans e2a-essai."""
    stray = sorted(run_profiles - trial_profiles)
    if stray:
        raise SystemExit(f"séries de profils qui ne sont pas des profils d'essai {stray} : fichiers à retirer "
                         "de data/experiments/e2a-essai/runs")


def check_analysis_failure(question_id: str, analysis: dict, profile_name: str) -> None:
    """Un mauvais fournisseur est systématique (profil mal décrit) : inutile de payer les
    questions suivantes. Les autres indisponibilités sont transitoires et rejouables."""
    error = analysis.get("error") or ""
    if not analysis.get("available") and error.startswith("LlmProviderMismatchError"):
        raise SystemExit(f"{question_id} : {error[:200]}\nmesure interrompue : vérifier provider_name du "
                         f"profil {profile_name} dans RAG/config.yaml (champ provider de la réponse de chat)")


def permanent_error_exit(exc: Exception) -> SystemExit:
    """Erreur permanente (clé, crédit, réponse coupée) : message court, sans trace d'appel.
    Les messages du client OpenRouter ne citent ni la clé ni le corps des réponses."""
    message = f"mesure interrompue, erreur permanente : {type(exc).__name__}: {exc}"
    if hasattr(exc, "cost_usd"):
        cost = exc.cost_usd
        message += f"\ncoût de la réponse inexploitable : {'inconnu' if cost is None else f'{cost} $'}"
    return SystemExit(message)


def check_run_manifest(name: str, manifest: dict, *, questions_sha: str, prompt_version: str, prompt_sha: str,
                       k: int) -> None:
    """Refuse une mesure incohérente avec les questions, le prompt (version et empreinte), k
    ou son propre nom de fichier."""
    profile, _, rest = name.partition("__")
    mode, _, suffix = rest.partition("__")
    if manifest["questions_sha256"] != questions_sha:
        raise SystemExit(f"{name} : questions modifiées depuis la mesure, remesurer")
    if manifest["prompt_version"] != prompt_version:
        raise SystemExit(f"{name} : version de prompt {manifest['prompt_version']} différente de {prompt_version}")
    if manifest.get("prompt_sha256") != prompt_sha:
        raise SystemExit(f"{name} : prompt modifié depuis la mesure (empreinte différente), remesurer")
    if manifest["k"] != k:
        raise SystemExit(f"{name} : k = {manifest['k']} au lieu de {k}")
    if (manifest["profile"], manifest["mode"], bool(manifest["exact"])) != (profile, mode, suffix == "exact"):
        raise SystemExit(f"{name} : le manifeste (profil, mode, exact) ne correspond pas au nom du fichier")


def check_runs_consistency(manifests: dict[str, dict]) -> None:
    """Toutes les mesures partagent le modèle d'embedding et la configuration (sections
    `search` et `llm`) ; un profil garde son modèle et son fournisseur."""
    fingerprints = {m["embedding_fingerprint"] for m in manifests.values()}
    if len(fingerprints) > 1:
        raise SystemExit("modèle d'embedding différent entre les mesures : remesurer")
    configs = {m.get("config_sha256") for m in manifests.values()}
    if len(configs) > 1 or None in configs:
        raise SystemExit("configuration (search, llm) différente ou absente entre les mesures : remesurer")
    seen: dict[str, tuple] = {}
    for name, m in manifests.items():
        pair = (m["model"], m["provider_tag"])
        if seen.setdefault(m["profile"], pair) != pair:
            raise SystemExit(f"{name} : modèle ou fournisseur différent des autres mesures du profil {m['profile']}")


def check_index_matches_truth(manifests: dict[str, dict], truth_sha: str) -> None:
    """Les mesures doivent porter sur le corpus de la vérité terrain : même ensemble de
    `doc_id` dans l'index (au moment de chaque mesure) que dans le Gold lu par verite-terrain."""
    missing = sorted(name for name, m in manifests.items() if not m.get("index_doc_ids_sha256"))
    if missing:
        raise SystemExit(f"{missing} : empreinte de l'index absente du manifeste, remesurer")
    if len({m["index_doc_ids_sha256"] for m in manifests.values()}) > 1:
        raise SystemExit("index différent entre les mesures (réindexation entre deux séries) : remesurer")
    if next(iter(manifests.values()))["index_doc_ids_sha256"] != truth_sha:
        raise SystemExit("l'index mesuré ne contient pas les documents de la vérité terrain : "
                         "relancer verite-terrain sur le Gold indexé, ou réindexer")


def check_complete_field(full_profiles: set[str], configured: set[str]) -> None:
    """Les séries « full » doivent couvrir exactement les profils configurés."""
    missing = sorted(configured - full_profiles)
    if missing:
        raise SystemExit(f"mesures « full » manquantes pour {missing} : pas de décision sur un champ incomplet")
    extra = sorted(full_profiles - configured)
    if extra:
        raise SystemExit(f"mesures « full » de profils non configurés {extra} : fichiers périmés à retirer "
                         "de data/experiments/e2a/runs")


# --- Sous-commandes --------------------------------------------------------------------

def cmd_verite_terrain(args) -> None:
    from RAG.experiments.comparaison_embeddings import _all_documents, _diseases_by_doc, _relevance
    from RAG.src.retrieval.identifiers import extract_identifiers
    from RAG.src.retrieval.retriever import doc_ids_sha256

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
            expected = exact_doc_ids(documents, extract_identifiers(q["question"]))
            if expected != set(rule["doc_ids"]):
                raise SystemExit(f"{q['id']} : documents exacts attendus {sorted(expected)} "
                                 f"mais déclarés {sorted(rule['doc_ids'])}")
            relevant[q["id"]] = list(rule["doc_ids"])
        elif q["part"] == 1:
            mask = _relevance(q, documents, diseases)
            relevant[q["id"]] = [doc_ids[i] for i in np.flatnonzero(mask)]
        else:
            relevant[q["id"]] = []
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"questions_sha256": _sha256(QUESTIONS_PATH),
                "gold_doc_ids_sha256": doc_ids_sha256(doc_ids)}
    (OUT / "verite_terrain.json").write_text(json.dumps({"manifest": manifest, "relevant": relevant}),
                                             encoding="utf-8")
    print(f"vérité terrain : {len(relevant)} questions")


def cmd_mesurer(args) -> None:
    from RAG.src.retrieval.retriever import Searcher
    from RAG.src.utils.config import load_search_config
    from RAG.src.utils.errors import LlmPermanentError

    questions = _load_questions()
    out = output_dir(load_search_config(profile=args.profile))
    results, failures = {}, []
    try:
        with Searcher(profile_name=args.profile, cache_path=out / "cache_analyses.json") as searcher:
            profile = searcher.config.analysis_profile
            index_sha = searcher.index_doc_ids_sha256()
            for q in questions:
                r = searcher.search(q["question"], mode=args.mode,
                                    force_exact=True if args.exact else None).as_dict()
                analysis = r["trace"]["analysis"]
                check_analysis_failure(q["id"], analysis, profile.name)
                if not analysis["available"]:
                    failures.append(f"{q['id']} : {analysis['error']}")
                results[q["id"]] = {"doc_ids": [d["doc_id"] for d in r["documents"]],
                                    "stages": [d["stage"] for d in r["documents"]], "flags": r["trace"]["flags"],
                                    "identifiers": r["trace"]["identifiers"], "analysis": analysis,
                                    "timings_ms": r["trace"]["timings_ms"]}
            if searcher.index_doc_ids_sha256() != index_sha:
                raise SystemExit("index modifié pendant la mesure (indexation concurrente) : remesurer")
    except LlmPermanentError as exc:
        raise permanent_error_exit(exc) from None
    if failures:
        raise SystemExit("analyses indisponibles, mesure non enregistrée (relancer ; le cache garde les "
                         "réussites) :\n" + "\n".join(failures))
    from RAG.src.prompts.analysis import PROMPT_SHA, PROMPT_VERSION
    from RAG.src.utils.config import DEFAULT_CONFIG_PATH, load_config
    manifest = {"questions_sha256": _sha256(QUESTIONS_PATH), "profile": profile.name, "model": profile.model,
                "provider_tag": profile.provider_tag, "prompt_version": PROMPT_VERSION,
                "prompt_sha256": PROMPT_SHA, "mode": args.mode,
                "exact": bool(args.exact), "k": searcher.config.k,
                "embedding_fingerprint": load_config().embedding.fingerprint,
                "config_sha256": config_sha256(yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))),
                "index_doc_ids_sha256": index_sha}
    name = f"{profile.name}__{args.mode}{'__exact' if args.exact else ''}.json"
    (out / "runs").mkdir(parents=True, exist_ok=True)
    (out / "runs" / name).write_text(json.dumps({"manifest": manifest, "results": results}, ensure_ascii=False),
                                     encoding="utf-8")
    print(f"{name} : {len(results)} questions")


def _median_latency(run: dict) -> float:
    values = [r["analysis"].get("latency_ms") or 0.0 for r in run["results"].values()]
    return float(np.median(values))


def _load_field(runs_dir: Path) -> tuple[list[dict], dict[str, set[str]], dict[str, dict]]:
    """Questions, vérité terrain (toujours celle de e2a, lue seulement) et séries de
    `runs_dir`, après tous les contrôles de cohérence."""
    from RAG.src.prompts.analysis import PROMPT_SHA, PROMPT_VERSION

    questions = _load_questions()
    questions_sha = _sha256(QUESTIONS_PATH)
    truth = json.loads((OUT / "verite_terrain.json").read_text(encoding="utf-8"))
    if truth["manifest"]["questions_sha256"] != questions_sha:
        raise SystemExit("vérité terrain calculée sur d'autres questions : relancer verite-terrain")
    relevant = {qid: set(ids) for qid, ids in truth["relevant"].items()}
    loaded = {}
    for path in sorted(runs_dir.glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        check_run_manifest(path.stem, run["manifest"], questions_sha=questions_sha,
                           prompt_version=PROMPT_VERSION, prompt_sha=PROMPT_SHA, k=K)
        loaded[path.stem] = run
    if not loaded:
        raise SystemExit(f"aucune mesure dans data/experiments/{runs_dir.parent.name}/runs")
    check_runs_consistency({n: r["manifest"] for n, r in loaded.items()})
    check_index_matches_truth({n: r["manifest"] for n, r in loaded.items()},
                              truth["manifest"]["gold_doc_ids_sha256"])
    print(f"Vérité terrain : Gold {truth['manifest']['gold_doc_ids_sha256'][:12]}, "
          f"questions {questions_sha[:12]}\n")
    return questions, relevant, loaded


def _scores_of(run: dict, questions: list[dict], relevant: dict[str, set[str]]) -> dict[str, float]:
    return {q["id"]: score_question(q, run["results"][q["id"]]["doc_ids"], run["results"][q["id"]]["flags"],
                                    run["results"][q["id"]]["identifiers"], relevant[q["id"]], K,
                                    stages=run["results"][q["id"]].get("stages"))
            for q in questions}


def _groups(s: dict[str, float], questions: list[dict]) -> list[list[float]]:
    """Scores regroupés : P1-A, P1-B, P1-C, P2, P3."""
    groups = [[s[q["id"]] for q in questions if q["part"] == 1 and q["family"] == fam] for fam in "ABC"]
    return groups + [[s[q["id"]] for q in questions if q["part"] == part] for part in (2, 3)]


def _print_part2(full: dict, scored: dict, questions: list[dict]) -> bool:
    """Critère d'acceptation, affiché profil par profil ; vrai s'il échoue."""
    print("## Critère d'acceptation : partie 2 à 100 %\n")
    failed = False
    for profile in full:
        s = scored[f"{profile}__full"]
        part2 = [s[q["id"]] for q in questions if q["part"] == 2]
        failed = failed or not all(part2)
        print(f"- {profile} : {sum(part2):.0f}/{len(part2)} {'OK' if all(part2) else 'ÉCHEC'}")
    return failed


def _print_ablation(profile: str, scored: dict, loaded: dict, questions: list[dict]) -> None:
    """Apport de chaque ingrédient (V0 à V3) et diagnostic HNSW pour un profil."""
    print("| Version | P1-A | P1-B | P1-C | P2 | P3 |\n|---|---|---|---|---|---|")
    v0 = load_v0_scores(E1_SCORES_PATH, questions)
    if v0 is not None:
        print("| V0 E1 (anglais) | " + " | ".join(f"{np.mean(v0[f]):.3f}" for f in "ABC") + " | — | — |")
    else:
        print("| V0 E1 (anglais) | (scores E1 absents) |||||")
    for label, mode in (("V1 similarité", "similarity"), ("V2 + filtres", "filters"), ("V3 complète", "full")):
        s = scored.get(f"{profile}__{mode}")
        if not s:
            print(f"| {label} | (mesure absente) |||||")
            continue
        print(f"| {label} | " + " | ".join(f"{np.mean(g):.3f}" for g in _groups(s, questions)) + " |")
    print("\nV0 = questions anglaises, recherche exacte sur tout le corpus, présélection filter_gene en "
          "famille B (protocole E1) ; l'écart V0→V1 n'isole donc pas le seul effet du français et de l'analyse.")

    exact_run = loaded.get(f"{profile}__similarity__exact")
    approx_run = loaded.get(f"{profile}__similarity")
    if exact_run and approx_run:
        overlaps = [len(set(exact_run["results"][q["id"]]["doc_ids"]) & set(approx_run["results"][q["id"]]["doc_ids"]))
                    / max(1, len(exact_run["results"][q["id"]]["doc_ids"])) for q in questions]
        print(f"\nDiagnostic : recouvrement moyen HNSW / exacte sans filtre = {np.mean(overlaps):.3f}")


def cmd_evaluer(args) -> None:
    from RAG.src.utils.config import load_search_config

    questions, relevant, loaded = _load_field(OUT / "runs")
    scored = {n: _scores_of(r, questions, relevant) for n, r in loaded.items()}
    full = {n.split("__")[0]: r for n, r in loaded.items() if n.endswith("__full")}
    check_complete_field(set(full), set(load_search_config().profiles))

    if _print_part2(full, scored, questions):
        raise SystemExit("critère partie 2 non atteint : bug à corriger avant toute décision")

    costs = {p: sum(r["results"][q["id"]]["analysis"]["cost_usd"] for q in questions) for p, r in full.items()}
    per_q = {p: [scored[f"{p}__full"][q["id"]] for q in questions] for p in full}
    choice, details = choose_model(per_q, costs)
    print("\n## Choix du modèle d'analyse (règle fixée d'avance)\n")
    print("| Profil | Score moyen | Coût total ($) | Exactitude signification | Latence médiane (ms) |\n|---|---|---|---|---|")
    for p, run in full.items():
        analyses = {qid: res["analysis"] for qid, res in run["results"].items()}
        print(f"| {p} | {details['means'][p]:.3f} | {costs[p]:.4f} | "
              f"{significance_accuracy(questions, analyses):.3f} | {_median_latency(run):.0f} |")
    print("\nLatence : celle de l'appel d'origine ; un rejeu depuis le cache la conserve.")
    for p, iv in details["intervals"].items():
        print(f"- {details['best']} − {p} : {iv['ecart']:+.3f}, IC 95 % [{iv['ic_bas']:+.3f}, {iv['ic_haut']:+.3f}]")
    print(f"\nDécision : **{choice}** (meilleur : {details['best']} ; indistinguables : {details['indistinguishable']})")

    print("\n## Apport de chaque ingrédient (profil retenu)\n")
    _print_ablation(choice, scored, loaded, questions)


def cmd_evaluer_essai(args) -> None:
    """Mêmes contrôles et scores que `evaluer`, sur les séries d'essai, sans choix de modèle.
    Le critère de la partie 2 est affiché ; s'il échoue, tout est affiché puis la commande
    sort en erreur."""
    from RAG.src.utils.config import load_search_config

    print("# Essai de validation de la chaîne — ne sert pas au choix du modèle\n")
    questions, relevant, loaded = _load_field(OUT_ESSAI / "runs")
    check_trial_field({r["manifest"]["profile"] for r in loaded.values()},
                      set(load_search_config().trial_profiles))
    scored = {n: _scores_of(r, questions, relevant) for n, r in loaded.items()}
    full = {n.split("__")[0]: r for n, r in loaded.items() if n.endswith("__full")}
    if not full:
        raise SystemExit("aucune série « full » dans data/experiments/e2a-essai/runs")

    failed = _print_part2(full, scored, questions)

    print("\n## Scores par partie et famille (série « full »)\n")
    print("| Profil | Score moyen | P1-A | P1-B | P1-C | P2 | P3 | Exactitude signification | "
          "Latence médiane (ms) |\n|---|---|---|---|---|---|---|---|---|")
    for p, run in full.items():
        s = scored[f"{p}__full"]
        analyses = {qid: res["analysis"] for qid, res in run["results"].items()}
        print(f"| {p} | {np.mean(list(s.values())):.3f} | "
              + " | ".join(f"{np.mean(g):.3f}" for g in _groups(s, questions))
              + f" | {significance_accuracy(questions, analyses):.3f} | {_median_latency(run):.0f} |")
    print("\nLatence : celle de l'appel d'origine ; un rejeu depuis le cache la conserve. "
          "Coût : nul (offre gratuite).")

    for p in full:
        print(f"\n## Apport de chaque ingrédient (profil d'essai {p})\n")
        _print_ablation(p, scored, loaded, questions)

    if failed:
        raise SystemExit("critère partie 2 non atteint pendant l'essai : bug à corriger avant la mesure officielle")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)
    sub.add_parser("verite-terrain").set_defaults(func=cmd_verite_terrain)
    p = sub.add_parser("mesurer")
    p.add_argument("--profile", required=True)
    p.add_argument("--mode", choices=("similarity", "filters", "full"), required=True)
    p.add_argument("--exact", action="store_true", help="force la recherche exacte (diagnostic HNSW)")
    p.set_defaults(func=cmd_mesurer)
    p = sub.add_parser("evaluer")
    p.add_argument("--essai", action="store_true",
                   help="évalue les séries de l'essai gratuit (data/experiments/e2a-essai), sans choix de modèle")
    p.set_defaults(func=lambda a: (cmd_evaluer_essai if a.essai else cmd_evaluer)(a))
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
