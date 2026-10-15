"""Ingestion des concepts MedGen par panel dans la couche raw."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import RAW
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.medgen import extract_medgen_cuis, fetch_medgen_concept
from ingestion.storage import (
    begin_partition,
    build_manifest,
    finalize_partition,
    open_stream,
    partition_uri,
    put_bytes,
)
from scripts.ingest_ncbi_gene import build_client

OBJECT_NAME = "concepts.jsonl.gz"
BULK_OBJECT = "variant_summary.txt.gz"


def cuis_from_raw_clinvar(
    clinvar_partition: str, genes: list[str], client=None
) -> list[str]:
    """Extrait les CUI MedGen du bulk ClinVar brut, pour les gènes du panel.

    MedGen a une dépendance de données sur ClinVar : les CUI viennent du champ
    `PhenotypeIDS`. Cette lecture pilote les appels d'API et ne persiste rien.

    Le bulk est parcouru en flux : 442 Mo compressés, ~4 Go décompressés. La chaîne
    `open_stream` -> `GzipFile` -> `TextIOWrapper` -> `DictReader` ne tient qu'une
    ligne à la fois en mémoire.
    """
    genes_set = set(genes)
    cuis: list[str] = []

    with open_stream(f"{clinvar_partition}/{BULK_OBJECT}", client=client) as raw:
        with gzip.GzipFile(fileobj=raw, mode="rb") as decompressed:
            reader = csv.DictReader(
                io.TextIOWrapper(decompressed, encoding="utf-8"), delimiter="\t"
            )
            for row in reader:
                if row.get("GeneSymbol") not in genes_set:
                    continue
                for cui in extract_medgen_cuis(row.get("PhenotypeIDS") or ""):
                    if cui not in cuis:
                        cuis.append(cui)
    return cuis


def ingest_medgen(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose les concepts MedGen du panel dans la couche raw, XML `conceptmeta` intact."""
    clinvar_partition = partition_uri(RAW, "clinvar", logical_date, lake_uri=lake_uri)
    cuis = cuis_from_raw_clinvar(clinvar_partition, genes)

    records = [
        {"cui": cui, "esummary": fetch_medgen_concept(client, cui)} for cui in cuis
    ]
    partition = partition_uri(RAW, "medgen", logical_date, panel=panel, lake_uri=lake_uri)
    begin_partition(partition)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="medgen",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=medgen",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les concepts MedGen dans la couche raw.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_medgen(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
