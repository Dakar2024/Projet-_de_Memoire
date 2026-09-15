"""Ingestion des détails de termes HPO par panel dans la couche raw."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import RAW
from ingestion.hpo import HP_TERMS_URL, fetch_hpo_term_details, parse_genes_to_phenotype
from ingestion.jsonl import dumps_gzipped
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    get_bytes,
    partition_uri,
    put_bytes,
)

OBJECT_NAME = "hpo_terms.jsonl.gz"
GENES_TO_PHENOTYPE_OBJECT = "genes_to_phenotype.txt"


def ingest_hpo_terms(
    logical_date: str, panel: str, genes: list[str], lake_uri: str | None = None
) -> str:
    """Dépose les détails des termes HPO du panel dans la couche raw.

    Les IDs viennent du fichier plat déposé par le DAG d'acquisition ; leur
    enrichissement dépend des gènes du panel, d'où le partitionnement `panel=`.
    """
    hpo_partition = partition_uri(RAW, "hpo", logical_date, lake_uri=lake_uri)
    flat = get_bytes(f"{hpo_partition}/{GENES_TO_PHENOTYPE_OBJECT}")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(flat)
        flat_path = Path(handle.name)
    try:
        rows = parse_genes_to_phenotype(flat_path, genes)
    finally:
        flat_path.unlink(missing_ok=True)

    details = fetch_hpo_term_details([row["hpo_id"] for row in rows])
    # Une ligne déposée par ligne du panel, même quand l'API ne reconnaît plus le
    # terme (retiré ou fusionné) : ses détails restent vides plutôt que la ligne ne
    # disparaisse. Construire les enregistrements depuis la réponse de l'API perdrait
    # silencieusement ces termes, comme pour un CUI MedGen non résolu.
    records = [
        {**row, "details": details.get(row["hpo_id"], {})} for row in rows
    ]

    partition = partition_uri(RAW, "hpo_terms", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="hpo_terms",
            logical_date=logical_date,
            source_url=HP_TERMS_URL,
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les détails de termes HPO dans la couche raw.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_hpo_terms(
        args.logical_date, args.panel, args.genes.split(","), lake_uri=args.lake_uri,
    ))
