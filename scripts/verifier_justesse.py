"""Niveau 7 d'E3b : justesse des variants du Silver contre ClinVar.

7b, automatique : `--tirage` fige l'échantillon (identifiants) pour qu'il soit rejouable ;
`--comparer` interroge les E-utilities par lots et écrit le détail (`comparaisons.csv`) et le bilan
(`resume.json`).
7a, manuel : `--grille` pré-remplit la grille des onze fiches du protocole avec nos valeurs
(`grille_justesse_e3b.md` dans le dossier de sortie, le dépôt étant monté en lecture seule dans le
scheduler ; copiée ensuite dans `reference/`), que l'utilisateur confronte au site de ClinVar.
Lecture seule du lac : à lancer dans le scheduler principal, hors de tout run (quota NCBI).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl

from evaluation.clinvar_agreement import (
    ClinvarSummary,
    Comparison,
    SilverVariant,
    Verdict,
    compare,
    parse_rcv_conditions,
    wilson_interval,
)
from ingestion.storage import storage_options
from transformations.silver_io import read_silver
from transformations.silver_to_gold_rag import documents_uri

SAMPLE_SIZE = 400
SEED = 20261023
BATCH_SIZE = 200
# Un XML VCV pèse jusqu'à quelques centaines de Ko : lots plus petits que pour l'esummary.
XML_BATCH_SIZE = 20
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "experiments" / "e3b"
FIELDS = ("name", "significance", "review_status", "last_evaluated", "rs_dbsnp", "diseases")
GRID_NAME = "grille_justesse_e3b.md"
# Motifs qu'un document RAG ne doit jamais contenir (`reference/evaluation.md` § 8.4).
SENTINEL_PATTERNS = ("rs-1", "None", "Last evaluated: -.", "Review status: -")
VERDICT_CELL = "☐ conforme ☐ mise à jour postérieure ☐ **écart**"


@dataclass(frozen=True)
class ProtocolCase:
    """Un des onze variants du protocole (§ 8.2), et le cas qu'il représente s'il faut le remplacer."""

    number: int
    variation_id: str
    label: str
    # Colonnes du Silver `clinvar_variant` et valeurs attendues ; `rs_dbsnp: -1` = sans dbSNP.
    criteria: dict[str, object]


PROTOCOL_CASES = (
    ProtocolCase(1, "37392", "BRCA1 pathogène/probablement pathogène", {
        "genesymbol": "BRCA1", "clinicalsignificance": "Pathogenic/Likely pathogenic",
    }),
    ProtocolCase(2, "1012631", "BRCA2 pathogène, un soumetteur", {
        "genesymbol": "BRCA2", "clinicalsignificance": "Pathogenic",
        "reviewstatus": "criteria provided, single submitter",
    }),
    ProtocolCase(3, "1023669", "ATM probablement pathogène, panel d'experts", {
        "genesymbol": "ATM", "clinicalsignificance": "Likely pathogenic",
        "reviewstatus": "reviewed by expert panel",
    }),
    ProtocolCase(4, "96762", "BRCA2 bénin, panel d'experts", {
        "genesymbol": "BRCA2", "clinicalsignificance": "Benign", "reviewstatus": "reviewed by expert panel",
    }),
    ProtocolCase(5, "1017479", "BARD1 probablement bénin", {
        "genesymbol": "BARD1", "clinicalsignificance": "Likely benign",
    }),
    ProtocolCase(6, "1013569", "PTEN de signification incertaine", {
        "genesymbol": "PTEN", "clinicalsignificance": "Uncertain significance",
    }),
    ProtocolCase(7, "1764023", "BRCA2 conflictuel", {
        "genesymbol": "BRCA2", "clinicalsignificance": "Conflicting classifications of pathogenicity",
    }),
    ProtocolCase(8, "1018969", "PTEN pathogène sans dbSNP", {
        "genesymbol": "PTEN", "clinicalsignificance": "Pathogenic", "rs_dbsnp": -1,
    }),
    ProtocolCase(9, "1336926", "multi-gènes TP53;WRAP53", {"genesymbol": "TP53;WRAP53"}),
    ProtocolCase(10, "1014228", "G6PD conflictuel (drépanocytose)", {
        "panel": "sickle", "genesymbol": "G6PD",
        "clinicalsignificance": "Conflicting classifications of pathogenicity",
    }),
    ProtocolCase(11, "1048666", "HBB pathogène sans dbSNP ni critères (drépanocytose)", {
        "panel": "sickle", "genesymbol": "HBB", "clinicalsignificance": "Pathogenic",
        "reviewstatus": "no assertion criteria provided", "rs_dbsnp": -1,
    }),
)


@dataclass(frozen=True)
class GridEntry:
    """Une fiche de la grille : nos valeurs d'octobre et le document RAG produit."""

    case: ProtocolCase
    # Identifiant du protocole remplacé, s'il a disparu du Gold.
    replaced_from: str | None
    variant: SilverVariant
    genesymbol: str
    clinvar_url: str
    document: str


def allocate(counts: dict[str, int], size: int) -> dict[str, int]:
    """Répartit `size` tirages proportionnellement aux effectifs (plus forts restes, ex aequo par nom)."""
    total = sum(counts.values())
    if size > total:
        raise ValueError(f"échantillon de {size} pour une population de {total}")
    quotas = {key: size * count / total for key, count in counts.items()}
    shares = {key: math.floor(quota) for key, quota in quotas.items()}
    by_remainder = sorted(quotas, key=lambda key: (shares[key] - quotas[key], key))
    for key in by_remainder[: size - sum(shares.values())]:
        shares[key] += 1
    return shares


def draw_sample(current: pl.DataFrame, size: int, seed: int) -> list[dict[str, str]]:
    """Tire `size` variants (`variationid`, `panel`) au prorata des panels ; trié d'abord, donc rejouable."""
    ordered = current.select("variationid", "panel").sort("variationid")
    counts = dict(ordered.group_by("panel").len().iter_rows())
    sample = []
    for panel, n in sorted(allocate(counts, size).items()):
        drawn = ordered.filter(pl.col("panel") == panel).sample(n, seed=seed)
        sample += [{"variation_id": row[0], "panel": panel} for row in drawn.sort("variationid").iter_rows()]
    return sample


def summarize(comparisons: list[Comparison]) -> dict:
    """Bilan : comptes par verdict et par champ en écart, taux de concordance et intervalle de Wilson."""
    verdicts = Counter(comparison.verdict.value for comparison in comparisons)
    compared = len(comparisons) - verdicts[Verdict.MISSING.value]
    agreeing = verdicts[Verdict.AGREES.value] + verdicts[Verdict.LATER_UPDATE.value]
    failed = Counter(
        check.field for comparison in comparisons for check in comparison.checks if not check.ok
    )
    return {
        "verdicts": {verdict.value: verdicts[verdict.value] for verdict in Verdict},
        "compared": compared,
        "agreement_rate": agreeing / compared if compared else None,
        "wilson_95": list(wilson_interval(agreeing, compared)) if compared else None,
        "failed_by_field": dict(sorted(failed.items())),
    }


def load_silver_variants(sample: list[dict[str, str]]) -> dict[str, SilverVariant]:
    """Lit dans le Silver courant les six valeurs comparées des variants tirés."""
    ids = [row["variation_id"] for row in sample]
    variants = read_silver("clinvar_variant").filter(
        pl.col("is_current") & pl.col("variationid").is_in(ids)
    )
    diseases = (
        read_silver("clinvar_variant_disease")
        .filter(pl.col("disease_name").is_not_null())
        .join(variants.select("alleleid", "panel"), on=["alleleid", "panel"])
        .group_by("alleleid", "panel")
        .agg(pl.col("disease_name").unique())
    )
    names = {(row["alleleid"], row["panel"]): row["disease_name"] for row in diseases.to_dicts()}
    return {
        row["variationid"]: SilverVariant(
            variation_id=row["variationid"],
            name=row["name"],
            significance=row["clinicalsignificance"],
            review_status=row["reviewstatus"],
            last_evaluated=row["lastevaluated"],
            rs_dbsnp=row["rs_dbsnp"],
            diseases=frozenset(names.get((row["alleleid"], row["panel"]), [])),
        )
        for row in variants.to_dicts()
    }


def fetch_summaries(client, ids: list[str]) -> dict[str, ClinvarSummary | None]:
    """Résumés ClinVar (esummary) et maladies des RCV (XML VCV), par lots ; `None` pour une fiche absente."""
    conditions: dict[str, frozenset[str]] = {}
    for start in range(0, len(ids), XML_BATCH_SIZE):
        xml = client.efetch(
            db="clinvar", uids=ids[start : start + XML_BATCH_SIZE], rettype="vcv", is_variationid="true"
        )
        conditions |= parse_rcv_conditions(xml)
    summaries: dict[str, ClinvarSummary | None] = {}
    for start in range(0, len(ids), BATCH_SIZE):
        records = client.esummary_many(db="clinvar", uids=ids[start : start + BATCH_SIZE])
        summaries |= {
            uid: ClinvarSummary.from_esummary(record, conditions.get(uid, frozenset()))
            for uid, record in records.items()
        }
    return summaries


def _csv_row(panel: str, comparison: Comparison) -> dict[str, str]:
    row = {"variation_id": comparison.variation_id, "panel": panel, "verdict": comparison.verdict.value}
    for check in comparison.checks:
        row[f"{check.field}_ok"] = "1" if check.ok else "0"
        # Les deux valeurs seulement en écart : le CSV reste lisible.
        if not check.ok:
            row[f"{check.field}_ours"] = check.ours
            row[f"{check.field}_theirs"] = check.theirs
    return row


def resolve_sample(
    cases: list[ProtocolCase], candidates: pl.DataFrame, seed: int
) -> list[tuple[ProtocolCase, str, str | None]]:
    """Garde chaque variant encore présent ; sinon tire un variant du même cas (graine fixe, sans doublon)."""
    ordered = candidates.sort("variationid")
    present = set(ordered["variationid"].to_list())
    taken = {case.variation_id for case in cases if case.variation_id in present}
    resolved = []
    for case in cases:
        if case.variation_id in present:
            resolved.append((case, case.variation_id, None))
            continue
        matching = ordered.filter(
            *[pl.col(column) == value for column, value in case.criteria.items()],
            ~pl.col("variationid").is_in(list(taken)),
        )
        if matching.is_empty():
            raise ValueError(f"cas n° {case.number} « {case.label} » : aucun variant de remplacement")
        chosen = matching.sample(1, seed=seed)["variationid"].item()
        taken.add(chosen)
        resolved.append((case, chosen, case.variation_id))
    return resolved


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _dbsnp(rs_dbsnp: int) -> str:
    return "aucun (`-1`)" if rs_dbsnp == -1 else f"rs{rs_dbsnp}"


def _render_entry(entry: GridEntry) -> list[str]:
    variant = entry.variant
    title = f"### {entry.case.number} — {entry.case.label}"
    origin = (
        f"Variant de remplacement : remplace {entry.replaced_from}, absent du Gold."
        if entry.replaced_from else "Variant du protocole (§ 8.2), présent dans le Gold."
    )
    diseases = "<br>".join(_cell(name) for name in sorted(variant.diseases)) or "aucune"
    return [
        title,
        "",
        f"Fiche : {entry.clinvar_url} — gène(s) `{entry.genesymbol}`. {origin}",
        "",
        "| Élément | Notre valeur (Silver) | Conforme à la fiche |",
        "|---|---|---|",
        f"| Nom HGVS (titre, au caractère près) | `{_cell(variant.name)}` | ☐ |",
        f"| Signification (Germline classification) | {_cell(variant.significance)} | ☐ |",
        f"| Statut de revue | {_cell(variant.review_status)} | ☐ |",
        f"| Last evaluated (le site peut être postérieur, jamais antérieur) | {variant.last_evaluated} | ☐ |",
        f"| dbSNP | {_dbsnp(variant.rs_dbsnp)} | ☐ |",
        f"| Maladies (les nôtres ⊆ onglet Conditions) | {diseases} | ☐ |",
        "",
        "Document RAG produit (`gold/rag/documents`) :",
        "",
        "```text",
        entry.document,
        "```",
        "",
        "- ☐ chaque fait du document se retrouve sur la fiche",
        f"- ☐ le lien de citation est bien {entry.clinvar_url}",
        "- ☐ aucune sentinelle (`rs-1`, `None`, `-`) dans le texte",
        "",
    ]


def render_grid(
    entries: list[GridEntry], sentinels: dict[str, int], annex: list[tuple[str, str, str, str]], month: str
) -> str:
    """Grille 7a en Markdown : une fiche par variant, la grille du § 11, les sentinelles et les sources annexes."""
    lines = [
        "# Grille de justesse E3b — niveau 7a",
        "",
        f"Générée par `scripts/verifier_justesse.py --grille` sur le Gold du mois {month}.",
        "Pour chaque fiche : ouvrir le lien, confronter les six éléments (`reference/evaluation.md`",
        "§ 8.3), cocher, puis reporter le verdict dans la grille ci-dessous. Appliquer les trois pièges",
        "du § 8.1 : une date du site **postérieure** à la nôtre fait d'un écart de signification ou de",
        "statut une mise à jour légitime ; une date **antérieure** est un écart en soi.",
        "",
        "**Maladies** : les nôtres viennent de **tous** les RCV de la fiche (correction P-E3b-1 du",
        "rapport), pas seulement de l'encadré germinal. Chercher une maladie absente de l'encadré dans",
        "la liste complète des conditions et des soumissions avant de la compter comme écart.",
        "",
        "## Fiches",
        "",
    ]
    for entry in entries:
        lines += _render_entry(entry)
    lines += [
        "## Grille",
        "",
        "| # | Variation | Nom HGVS | Signification | Statut de revue | Date | dbSNP | Maladies | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        dbsnp = "—" if entry.variant.rs_dbsnp == -1 else "☐"
        lines.append(
            f"| {entry.case.number} | {entry.variant.variation_id} | ☐ | ☐ | ☐ | ☐ | {dbsnp} | ☐ | {VERDICT_CELL} |"
        )
    lines += [
        "",
        f"**Taux de concordance = (conformes + mises à jour postérieures) / {len(entries)}** : ______",
        "",
        "## Sentinelles dans tous les documents RAG (automatique, § 8.4)",
        "",
        "| Motif | Documents qui le contiennent (attendu : 0) |",
        "|---|---|",
        *(f"| `{pattern}` | {count} |" for pattern, count in sentinels.items()),
        "",
        "## Sources annexes (§ 8.5)",
        "",
        "| Source | Élément | Notre valeur | Fiche de contrôle | Verdict |",
        "|---|---|---|---|---|",
        *(
            f"| {source} | {element} | {_cell(value)} | {url} | ☐ conforme ☐ écart |"
            for source, element, value, url in annex
        ),
        "",
    ]
    return "\n".join(lines)


def _preferred_medgen_name(conceptmeta_xml: str) -> str:
    """Premier nom préféré du XML de concept MedGen, avec sa source (`SAB`)."""
    for name in ET.fromstring(f"<root>{conceptmeta_xml}</root>").iter("Name"):
        if name.get("type") == "preferred":
            return f"{name.text} ({name.get('SAB')})"
    return "aucun nom préféré"


def load_annex() -> list[tuple[str, str, str, str]]:
    """Nos valeurs des cinq vérifications annexes du protocole, lues dans le Silver."""
    gene = read_silver("ncbi_gene").filter(pl.col("gene_symbol") == "BRCA1").row(0, named=True)
    refseq = read_silver("refseq_transcript").filter(pl.col("accession") == "NM_007294").row(0, named=True)
    medgen = read_silver("medgen_concept").filter(pl.col("cui") == "C1292231").row(0, named=True)
    hpo = read_silver("hpo_term").filter(pl.col("hpo_id") == "HP:0002027").row(0, named=True)
    dbsnp = read_silver("clinvar_variant").filter(
        pl.col("is_current") & (pl.col("rs_dbsnp") == 80357498)
    )["variationid"].to_list()
    return [
        ("NCBI Gene", "BRCA1 : description et localisation",
         f"{gene['description']} ; {gene['maplocation']}", "https://www.ncbi.nlm.nih.gov/gene/672"),
        ("RefSeq", "NM_007294 : version et gène",
         f"version {refseq['version']} ; {refseq['gene_symbol']}", "https://www.ncbi.nlm.nih.gov/nuccore/NM_007294.4"),
        ("MedGen", "C1292231 : libellé et MIM",
         f"{_preferred_medgen_name(medgen['conceptmeta_xml'])} ; MIM {medgen['mim_number']}",
         "https://www.ncbi.nlm.nih.gov/medgen/C1292231"),
        ("HPO", "HP:0002027 : nom et définition",
         f"{hpo['hpo_name']} — {hpo['definition']}", "https://ontology.jax.org/api/hp/terms/HP%3A0002027"),
        ("dbSNP", "rs80357498 : variant n° 1",
         f"variation(s) ClinVar {', '.join(dbsnp)}", "https://www.ncbi.nlm.nih.gov/snp/rs80357498"),
    ]


def run_grid(output: Path) -> None:
    uri = documents_uri()
    documents = pl.read_delta(uri, storage_options=storage_options(uri)).filter(pl.col("doc_type") == "variant")
    current = read_silver("clinvar_variant").filter(pl.col("is_current"))
    candidates = current.filter(pl.col("variationid").is_in(documents["clinvar_variation_id"].implode()))
    resolved = resolve_sample(list(PROTOCOL_CASES), candidates, SEED)
    ours = load_silver_variants([{"variation_id": variation_id} for _, variation_id, _ in resolved])
    genes = dict(current.select("variationid", "genesymbol").iter_rows())
    by_id = {row["clinvar_variation_id"]: row for row in documents.to_dicts()}
    entries = [
        GridEntry(
            case=case,
            replaced_from=replaced_from,
            variant=ours[variation_id],
            genesymbol=genes[variation_id],
            clinvar_url=by_id[variation_id]["clinvar_url"],
            document=by_id[variation_id]["text"],
        )
        for case, variation_id, replaced_from in resolved
    ]
    sentinels = {
        pattern: documents.filter(pl.col("text").str.contains(pattern, literal=True)).height
        for pattern in SENTINEL_PATTERNS
    }
    output.write_text(
        render_grid(entries, sentinels, load_annex(), current["valid_from"].max()[:7]), encoding="utf-8"
    )
    replaced = [entry.case.number for entry in entries if entry.replaced_from]
    print(f"grille écrite → {output} ; variants remplacés : {replaced or 'aucun'} ; sentinelles : {sentinels}")


def run_draw(output: Path) -> None:
    if output.exists():
        raise SystemExit(f"{output} existe déjà : le tirage est figé, le supprimer pour en refaire un.")
    current = read_silver("clinvar_variant").filter(pl.col("is_current"))
    sample = draw_sample(current, SAMPLE_SIZE, SEED)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "seed": SEED,
                "size": SAMPLE_SIZE,
                "silver_month": current["valid_from"].max(),
                "population": dict(sorted(current.group_by("panel").len().iter_rows())),
                "sample": sample,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"{len(sample)} variants tirés → {output}")


def run_compare(draw: Path, output_dir: Path) -> None:
    from scripts.ingest_ncbi_gene import build_client

    sample = json.loads(draw.read_text("utf-8"))["sample"]
    ours = load_silver_variants(sample)
    missing_in_silver = [row["variation_id"] for row in sample if row["variation_id"] not in ours]
    if missing_in_silver:
        raise SystemExit(f"variants tirés absents du Silver courant : {missing_in_silver[:10]}")
    theirs = fetch_summaries(build_client(), [row["variation_id"] for row in sample])
    comparisons = [compare(ours[row["variation_id"]], theirs.get(row["variation_id"])) for row in sample]

    rows = [_csv_row(row["panel"], comparison) for row, comparison in zip(sample, comparisons)]
    columns = ["variation_id", "panel", "verdict"] + [
        f"{field}_{suffix}" for field in FIELDS for suffix in ("ok", "ours", "theirs")
    ]
    with (output_dir / "comparaisons.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(comparisons)
    (output_dir / "resume.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--tirage", action="store_true", help="tirer et figer l'échantillon")
    action.add_argument("--comparer", action="store_true", help="comparer l'échantillon figé à ClinVar")
    action.add_argument("--grille", action="store_true", help="pré-remplir la grille 7a des onze fiches")
    parser.add_argument("--sortie", type=Path, default=OUTPUT_DIR, help="dossier des résultats")
    args = parser.parse_args()
    draw = args.sortie / "tirage.json"
    if args.grille:
        run_grid(args.sortie / GRID_NAME)
    elif args.tirage:
        run_draw(draw)
    else:
        run_compare(draw, args.sortie)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
