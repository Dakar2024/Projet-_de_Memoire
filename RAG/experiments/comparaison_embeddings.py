"""Comparaison BioBERT brut / NeuML PubMedBERT pour la partie sémantique de la
recherche (spec E1, §6).

Protocole :
- corpus complet, recherche exacte par force brute (on mesure le modèle, pas l'index) ;
- questions en anglais, sans identifiant (`rs`, HGVS) ;
- pertinence calculée sur les métadonnées, jamais jugée à la main ni par un LLM ;
- règle de décision fixée avant la mesure (`decide`).

Usage, dans l'ordre (voir reference/choix_embedding.md pour les commandes complètes) :
  lister-maladies     aide à rédiger les questions B et C à partir des données
  vectoriser          un passage par modèle, service démarré sur ce modèle
  verifier-questions  chaque question a-t-elle assez de documents pertinents ?
  evaluer             métriques, intervalle bootstrap, décision
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from ingestion.config import PANEL_GENES
from RAG.src.embeddings.embedder import EmbeddingClient
from RAG.src.ingestion.loader import load_gold_documents
from transformations.silver_io import read_silver

LABELS = ("biobert", "neuml")
QUESTIONS_PATH = Path(__file__).with_name("questions_embeddings.yaml")
MIN_RELEVANT = 10
K = 10


# --- Métriques (fonctions pures, testées) -----------------------------------------

def reciprocal_rank(scores: np.ndarray, target: int, candidates: np.ndarray | None = None) -> float:
    mask = np.ones_like(scores, dtype=bool) if candidates is None else candidates
    rank = 1 + int(np.sum(mask & (scores > scores[target])))
    return 1.0 / rank


def precision_at_k(
    scores: np.ndarray, relevant: np.ndarray, k: int = K, candidates: np.ndarray | None = None
) -> float:
    pool = np.flatnonzero(np.ones_like(scores, dtype=bool) if candidates is None else candidates)
    top = pool[np.argsort(-scores[pool], kind="stable")[:k]]
    return float(relevant[top].sum()) / k


def bootstrap_mean_ci(
    diffs, n_resamples: int = 10_000, seed: int = 20261001, alpha: float = 0.05
) -> tuple[float, float, float]:
    values = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n_resamples, len(values)))].mean(axis=1)
    return float(values.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def decide(mean: float, low: float) -> str:
    """Règle fixée avant la mesure : NeuML seulement si l'écart est positif et que
    l'intervalle de confiance exclut zéro. Sinon BioBERT, annoncé par le mémoire."""
    return "neuml" if mean > 0 and low > 0 else "biobert"


# --- Données ------------------------------------------------------------------------

def _all_documents() -> pl.DataFrame:
    return pl.concat([load_gold_documents(panel) for panel in PANEL_GENES]).sort("doc_id")


def _diseases_by_doc() -> pl.DataFrame:
    return (
        read_silver("clinvar_variant_disease")
        .filter(pl.col("disease_name").is_not_null())
        .select(pl.concat_str(pl.lit("clinvar:"), pl.col("alleleid").cast(pl.Utf8)).alias("doc_id"),
                pl.col("disease_name"))
        .unique()
    )


def _relevance(question: dict, documents: pl.DataFrame, diseases: pl.DataFrame) -> np.ndarray:
    rule = question["relevant"]
    if "doc_id" in rule:
        return (documents["doc_id"] == rule["doc_id"]).to_numpy()
    matching = diseases.filter(pl.col("disease_name").str.to_lowercase().str.contains(rule["disease_pattern"].lower(), literal=True))
    relevant = documents["doc_id"].is_in(matching["doc_id"].unique())
    if "gene" in rule:
        relevant &= documents["gene_symbol"] == rule["gene"]
    if "significance" in rule:
        relevant &= documents["clinical_significance"].is_in(rule["significance"])
    # Un document de gène n'a pas de signification : null compte comme non pertinent.
    return relevant.fill_null(False).to_numpy()


def _candidates(question: dict, documents: pl.DataFrame) -> np.ndarray | None:
    gene = question.get("filter_gene")
    return None if gene is None else (documents["gene_symbol"] == gene).to_numpy()


# --- Sous-commandes -------------------------------------------------------------------

def cmd_lister_maladies(args) -> None:
    documents = _all_documents()
    counts = (
        _diseases_by_doc().join(documents.select("doc_id", "gene_symbol"), on="doc_id")
        .group_by("gene_symbol", "disease_name").len().sort(["gene_symbol", "len"], descending=[False, True])
    )
    for gene in sorted(counts["gene_symbol"].unique()):
        print(f"\n## {gene}")
        for row in counts.filter(pl.col("gene_symbol") == gene).head(args.top).iter_rows(named=True):
            print(f"  {row['len']:6d}  {row['disease_name']}")


def cmd_vectoriser(args) -> None:
    client = EmbeddingClient(args.url, os.environ["RAG_EMBEDDINGS_API_KEY"], timeout_s=120)
    documents = _all_documents()
    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    texts = documents["text"].to_list()
    vectors = np.concatenate([client.embed(texts[i:i + 32]) for i in range(0, len(texts), 32)])
    np.save(out / f"{args.label}_docs.npy", vectors)
    np.save(out / f"{args.label}_questions.npy",
            np.concatenate([client.embed([q["question"] for q in questions[i:i + 32]])
                            for i in range(0, len(questions), 32)]))
    (out / "doc_ids.json").write_text(json.dumps(documents["doc_id"].to_list()), encoding="utf-8")
    print(f"{args.label} : {vectors.shape[0]} documents, {len(questions)} questions")


def cmd_verifier_questions(args) -> None:
    documents, diseases = _all_documents(), _diseases_by_doc()
    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    problems = 0
    for q in questions:
        relevant = _relevance(q, documents, diseases)
        candidates = _candidates(q, documents)
        if candidates is not None:
            relevant = relevant & candidates
        needed = 1 if q["family"] == "A" else MIN_RELEVANT
        status = "ok" if relevant.sum() >= needed else "INSUFFISANT"
        problems += status != "ok"
        print(f"{q['id']:5} {q['family']}  pertinents={int(relevant.sum()):6d}  {status}  {q['question']}")
    print(f"\n{len(questions)} questions, {problems} à corriger")


def cmd_evaluer(args) -> None:
    out = Path(args.out)
    documents, diseases = _all_documents(), _diseases_by_doc()
    if json.loads((out / "doc_ids.json").read_text(encoding="utf-8")) != documents["doc_id"].to_list():
        raise SystemExit("les documents ont changé depuis la vectorisation : revectoriser")
    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    scores = {label: [] for label in LABELS}
    for label in LABELS:
        docs = np.load(out / f"{label}_docs.npy")
        qvecs = np.load(out / f"{label}_questions.npy")
        for q, qvec in zip(questions, qvecs, strict=True):
            sims = docs @ qvec
            relevant = _relevance(q, documents, diseases)
            candidates = _candidates(q, documents)
            if q["family"] == "A":
                scores[label].append(reciprocal_rank(sims, int(np.flatnonzero(relevant)[0]), candidates))
            else:
                scores[label].append(precision_at_k(sims, relevant, K, candidates))
    diffs = np.array(scores["neuml"]) - np.array(scores["biobert"])
    mean, low, high = bootstrap_mean_ci(diffs)
    print("| Famille | n | BioBERT | NeuML |\n|---|---|---|---|")
    for family in ("A", "B", "C"):
        idx = [i for i, q in enumerate(questions) if q["family"] == family]
        print(f"| {family} | {len(idx)} | {np.mean([scores['biobert'][i] for i in idx]):.3f} "
              f"| {np.mean([scores['neuml'][i] for i in idx]):.3f} |")
    print(f"\nÉcart moyen NeuML − BioBERT : {mean:+.3f}, IC 95 % [{low:+.3f}, {high:+.3f}]")
    print(f"Décision (règle fixée avant la mesure) : {decide(mean, low)}")
    (out / "scores.json").write_text(json.dumps(scores), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("lister-maladies"); p.add_argument("--top", type=int, default=8); p.set_defaults(func=cmd_lister_maladies)
    p = sub.add_parser("vectoriser"); p.add_argument("--label", choices=LABELS, required=True)
    p.add_argument("--url", default="http://127.0.0.1:18080"); p.add_argument("--out", default="data/experiments")
    p.set_defaults(func=cmd_vectoriser)
    p = sub.add_parser("verifier-questions"); p.set_defaults(func=cmd_verifier_questions)
    p = sub.add_parser("evaluer"); p.add_argument("--out", default="data/experiments"); p.set_defaults(func=cmd_evaluer)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
