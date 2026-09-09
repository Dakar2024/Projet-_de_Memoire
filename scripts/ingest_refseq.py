"""Ingestion du catalogue des transcrits RefSeq par panel en Bronze."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import BRONZE
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.refseq import fetch_transcripts
from ingestion.storage import build_manifest, finalize_partition, partition_uri, put_bytes
from scripts.ingest_ncbi_gene import build_client

OBJECT_NAME = "transcripts.jsonl.gz"


def ingest_refseq(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose le catalogue des transcrits RefSeq du panel en Bronze.

    Un gène sans transcrit garde une entrée à liste vide : l'absence est une
    information, et le verdict qualité appartient à `check_bronze`.
    """
    records = [
        {"gene_symbol": gene, "transcripts": fetch_transcripts(client, gene)}
        for gene in genes
    ]
    partition = partition_uri(BRONZE, "refseq", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="refseq",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=nuccore",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les transcrits RefSeq en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_refseq(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
