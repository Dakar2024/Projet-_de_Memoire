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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    tirer = sub.add_parser("tirer")
    tirer.add_argument("--sortie", help="chemin du brouillon (défaut : le fichier du jeu)")
    tirer.set_defaults(func=cmd_tirer)
    sub.add_parser("verite-terrain").set_defaults(func=cmd_verite_terrain)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
