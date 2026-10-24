"""Niveau 7b d'E3b : tire des variants courants du Silver et les compare aux résumés ClinVar.

`--tirage` fige l'échantillon (identifiants) pour qu'il soit rejouable ; `--comparer` interroge
`esummary` par lots et écrit le détail (`comparaisons.csv`) et le bilan (`resume.json`).
Lecture seule du lac : à lancer dans le scheduler principal, hors de tout run (quota NCBI).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
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
from transformations.silver_io import read_silver

SAMPLE_SIZE = 400
SEED = 20261023
BATCH_SIZE = 200
# Un XML VCV pèse jusqu'à quelques centaines de Ko : lots plus petits que pour l'esummary.
XML_BATCH_SIZE = 20
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "experiments" / "e3b"
FIELDS = ("name", "significance", "review_status", "last_evaluated", "rs_dbsnp", "diseases")


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
    parser.add_argument("--sortie", type=Path, default=OUTPUT_DIR, help="dossier des résultats")
    args = parser.parse_args()
    draw = args.sortie / "tirage.json"
    if args.tirage:
        run_draw(draw)
    else:
        run_compare(draw, args.sortie)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
