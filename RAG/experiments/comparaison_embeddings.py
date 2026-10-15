"""Comparaison BioBERT brut / NeuML PubMedBERT pour la partie sémantique de la
recherche (spec E1, §6).

Protocole :
- corpus complet, recherche exacte par force brute (on mesure le modèle, pas l'index) ;
- questions en anglais, sans identifiant (`rs`, HGVS) ;
- pertinence calculée sur les métadonnées, jamais jugée à la main ni par un LLM ;
- règle de décision fixée avant la mesure (`decide`).

Usage, dans l'ordre (voir reference/choix_embedding.md pour les commandes complètes) :
  lister-maladies     aide à rédiger les questions B et C à partir des données
  vectoriser          un passage par modèle (--model-dir data/models/<modèle>), service
                      démarré sur ce modèle ; écrit <label>_manifest.json qui lie les
                      vecteurs au modèle, aux documents et aux questions
  verifier-questions  chaque question a-t-elle assez de documents pertinents ?
  evaluer             refuse si les manifestes ne concordent pas entre eux ou avec les
                      données actuelles, puis métriques, intervalle bootstrap, décision
"""

from __future__ import annotations

import argparse
import hashlib
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
MODEL_LABELS = {
    "dmis-lab/biobert-base-cased-v1.2": "biobert",
    "NeuML/pubmedbert-base-embeddings": "neuml",
}
SAME_MODEL_COSINE = 0.99


# --- Métriques (fonctions pures, testées) -----------------------------------------

def reciprocal_rank(scores: np.ndarray, target: int, candidates: np.ndarray | None = None) -> float:
    """Calcule le rang réciproque du document cible parmi les candidats."""
    mask = np.ones_like(scores, dtype=bool) if candidates is None else candidates
    rank = 1 + int(np.sum(mask & (scores > scores[target])))
    return 1.0 / rank


def precision_at_k(
    scores: np.ndarray, relevant: np.ndarray, k: int = K, candidates: np.ndarray | None = None
) -> float:
    """Calcule la précision des k premiers documents parmi les candidats."""
    pool = np.flatnonzero(np.ones_like(scores, dtype=bool) if candidates is None else candidates)
    top = pool[np.argsort(-scores[pool], kind="stable")[:k]]
    return float(relevant[top].sum()) / k


def bootstrap_mean_ci(
    diffs, n_resamples: int = 10_000, seed: int = 20261001, alpha: float = 0.05
) -> tuple[float, float, float]:
    """Calcule moyenne et IC bootstrap percentile des écarts appariés."""
    values = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n_resamples, len(values)))].mean(axis=1)
    return float(values.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def decide(mean: float, low: float) -> str:
    """Applique la règle fixée avant la mesure : NeuML seulement si l'écart est positif et son IC exclut zéro."""
    return "neuml" if mean > 0 and low > 0 else "biobert"


# --- Garde-fous : lier les vecteurs aux documents, questions et modèle ------------------

def _sha256(data: bytes) -> str:
    """Calcule le SHA-256 d'octets."""
    return hashlib.sha256(data).hexdigest()


def chunk_hash(chunk_ids) -> str:
    """Calcule l'empreinte des `chunk_id` dans l'ordre, pour détecter un texte Gold modifié."""
    return _sha256("\n".join(chunk_ids).encode("utf-8"))


def check_manifests(a, b, current_doc_ids, current_chunk_hash, current_questions_hash) -> None:
    """Refuse (SystemExit) deux vectorisations qui ne mesurent pas la même chose."""
    if a is None or b is None:
        raise SystemExit("manifeste manquant : vectoriser les deux modèles avant d'évaluer")
    if {a["label"], b["label"]} != set(LABELS):
        raise SystemExit(f"les étiquettes doivent être exactement {sorted(LABELS)}, "
                         f"reçues {sorted([a['label'], b['label']])}")
    if a["fingerprint"] == b["fingerprint"]:
        raise SystemExit("les deux modèles ont la même empreinte : ce n'est pas une comparaison")
    for m in (a, b):
        if m["doc_ids"] != current_doc_ids or m["doc_ids"] != a["doc_ids"]:
            raise SystemExit("les documents ont changé depuis la vectorisation : revectoriser")
        if m["chunk_hash"] != current_chunk_hash or m["chunk_hash"] != a["chunk_hash"]:
            raise SystemExit("le texte des documents a changé depuis la vectorisation : revectoriser")
        if m["questions_hash"] != current_questions_hash or m["questions_hash"] != a["questions_hash"]:
            raise SystemExit("les questions ont changé depuis la vectorisation : revectoriser")


def same_model_suspected(docs_a: np.ndarray, docs_b: np.ndarray, threshold: float = SAME_MODEL_COSINE) -> bool:
    """Signale deux « modèles » aux vecteurs quasi identiques (conteneur non remplacé)."""
    unit = lambda v: v / np.linalg.norm(v, axis=1, keepdims=True)  # noqa: E731
    mean_cosine = float(np.mean(np.sum(unit(docs_a) * unit(docs_b), axis=1)))
    return not mean_cosine < threshold  # NaN => suspect


# --- Données ------------------------------------------------------------------------

def _all_documents() -> pl.DataFrame:
    """Charge les documents Gold des deux panels, triés."""
    return pl.concat([load_gold_documents(panel) for panel in PANEL_GENES]).sort("doc_id")


def _diseases_by_doc() -> pl.DataFrame:
    """Associe chaque document de variant à ses noms de maladie (Silver)."""
    return (
        read_silver("clinvar_variant_disease")
        .filter(pl.col("disease_name").is_not_null())
        .select(pl.concat_str(pl.lit("clinvar:"), pl.col("alleleid").cast(pl.Utf8)).alias("doc_id"),
                pl.col("disease_name"))
        .unique()
    )


def _relevance(question: dict, documents: pl.DataFrame, diseases: pl.DataFrame) -> np.ndarray:
    """Calcule le masque des documents pertinents d'une question selon sa règle."""
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
    """Restreint les candidats au gène filtré, s'il y en a un."""
    gene = question.get("filter_gene")
    return None if gene is None else (documents["gene_symbol"] == gene).to_numpy()


# --- Sous-commandes -------------------------------------------------------------------

def cmd_lister_maladies(args) -> None:
    """Liste les maladies les plus fréquentes par gène, pour rédiger les questions."""
    documents = _all_documents()
    counts = (
        _diseases_by_doc().join(documents.select("doc_id", "gene_symbol"), on="doc_id")
        .group_by("gene_symbol", "disease_name").len().sort(["gene_symbol", "len"], descending=[False, True])
    )
    for gene in sorted(counts["gene_symbol"].unique()):
        print(f"\n## {gene}")
        for row in counts.filter(pl.col("gene_symbol") == gene).head(args.top).iter_rows(named=True):
            print(f"  {row['len']:6d}  {row['disease_name']}")


def _read_manifest(out: Path, label: str):
    """Lit le manifeste d'une vectorisation, ou None."""
    path = out / f"{label}_manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def cmd_vectoriser(args) -> None:
    """Vectorise le corpus et les questions avec le modèle servi."""
    export = json.loads((Path(args.model_dir) / "export.json").read_text(encoding="utf-8"))
    label = MODEL_LABELS.get(export["model_id"])
    if label is None:
        raise SystemExit(f"modèle inconnu : {export['model_id']!r}, attendu l'un de {sorted(MODEL_LABELS)}")
    if args.label is not None and args.label != label:
        raise SystemExit(f"--label {args.label} contredit le modèle de {args.model_dir} ({label})")
    client = EmbeddingClient(args.url, os.environ["RAG_EMBEDDINGS_API_KEY"], timeout_s=120)
    documents = _all_documents()
    questions_bytes = QUESTIONS_PATH.read_bytes()
    questions = yaml.safe_load(questions_bytes)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    texts = documents["text"].to_list()
    vectors = np.concatenate([client.embed(texts[i:i + 32]) for i in range(0, len(texts), 32)])
    qvectors = np.concatenate([client.embed([q["question"] for q in questions[i:i + 32]])
                               for i in range(0, len(questions), 32)])
    np.save(out / f"{label}_docs.npy", vectors)
    np.save(out / f"{label}_questions.npy", qvectors)
    manifest = {
        "label": label, "model_id": export["model_id"], "fingerprint": export["fingerprint"],
        "doc_ids": documents["doc_id"].to_list(),
        "chunk_hash": chunk_hash(documents["chunk_id"].to_list()),
        "questions_hash": _sha256(questions_bytes), "n_questions": len(questions),
        "docs_shape": list(vectors.shape), "questions_shape": list(qvectors.shape),
    }
    (out / f"{label}_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    print(f"{label} : {vectors.shape[0]} documents, {len(questions)} questions")


def cmd_verifier_questions(args) -> None:
    """Vérifie que chaque question a au moins un document pertinent."""
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
    """Compare les deux modèles et applique la règle de décision."""
    out = Path(args.out)
    documents, diseases = _all_documents(), _diseases_by_doc()
    questions_bytes = QUESTIONS_PATH.read_bytes()
    manifests = {label: _read_manifest(out, label) for label in LABELS}
    check_manifests(
        manifests["biobert"], manifests["neuml"], documents["doc_id"].to_list(),
        chunk_hash(documents["chunk_id"].to_list()), _sha256(questions_bytes),
    )
    questions = yaml.safe_load(questions_bytes)
    vectors = {}
    for label in LABELS:
        m = manifests[label]
        docs, qvecs = np.load(out / f"{label}_docs.npy"), np.load(out / f"{label}_questions.npy")
        if list(docs.shape) != m["docs_shape"] or list(qvecs.shape) != m["questions_shape"] \
                or len(questions) != m["n_questions"] or qvecs.shape[0] != len(questions):
            raise SystemExit(f"les vecteurs de {label} ne correspondent plus à leur manifeste : revectoriser")
        vectors[label] = (docs, qvecs)
    if same_model_suspected(vectors["biobert"][0], vectors["neuml"][0]):
        raise SystemExit("les deux vectorisations semblent venir du même modèle : "
                         "le service n'a pas été remplacé entre les deux passages")
    scores = {label: {} for label in LABELS}
    for label in LABELS:
        docs, qvecs = vectors[label]
        for q, qvec in zip(questions, qvecs, strict=True):
            sims = docs @ qvec
            relevant = _relevance(q, documents, diseases)
            candidates = _candidates(q, documents)
            if q["family"] == "A":
                scores[label][q["id"]] = reciprocal_rank(sims, int(np.flatnonzero(relevant)[0]), candidates)
            else:
                scores[label][q["id"]] = precision_at_k(sims, relevant, K, candidates)
    ids = [q["id"] for q in questions]
    diffs = np.array([scores["neuml"][i] - scores["biobert"][i] for i in ids])
    mean, low, high = bootstrap_mean_ci(diffs)
    print("| Famille | n | BioBERT | NeuML |\n|---|---|---|---|")
    for family in ("A", "B", "C"):
        fam = [q["id"] for q in questions if q["family"] == family]
        print(f"| {family} | {len(fam)} | {np.mean([scores['biobert'][i] for i in fam]):.3f} "
              f"| {np.mean([scores['neuml'][i] for i in fam]):.3f} |")
    print(f"\nÉcart moyen NeuML − BioBERT : {mean:+.3f}, IC 95 % [{low:+.3f}, {high:+.3f}]")
    print(f"Décision (règle fixée avant la mesure) : {decide(mean, low)}")
    print("\nPar famille, à titre indicatif, la décision reste celle de la règle globale :")
    for family in ("A", "B", "C"):
        fd = np.array([scores["neuml"][q["id"]] - scores["biobert"][q["id"]]
                       for q in questions if q["family"] == family])
        if len(fd):
            fm, fl, fh = bootstrap_mean_ci(fd)
            print(f"  {family} : écart {fm:+.3f}, IC 95 % [{fl:+.3f}, {fh:+.3f}] (n={len(fd)})")
    (out / "scores.json").write_text(json.dumps(scores), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """Point d'entrée en ligne de commande."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("lister-maladies"); p.add_argument("--top", type=int, default=8); p.set_defaults(func=cmd_lister_maladies)
    p = sub.add_parser("vectoriser"); p.add_argument("--model-dir", required=True)
    p.add_argument("--label", choices=LABELS, default=None, help="recoupement facultatif avec export.json")
    p.add_argument("--url", default="http://127.0.0.1:18080"); p.add_argument("--out", default="data/experiments")
    p.set_defaults(func=cmd_vectoriser)
    p = sub.add_parser("verifier-questions"); p.set_defaults(func=cmd_verifier_questions)
    p = sub.add_parser("evaluer"); p.add_argument("--out", default="data/experiments"); p.set_defaults(func=cmd_evaluer)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
