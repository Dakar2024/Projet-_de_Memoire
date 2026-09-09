"""Ingestion des métadonnées NCBI Gene par panel en Bronze."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from ingestion.config import BRONZE
from ingestion.http_client import NcbiClient
from ingestion.jsonl import dumps_gzipped
from ingestion.ncbi_gene import fetch_gene_info
from ingestion.storage import build_manifest, finalize_partition, partition_uri, put_bytes

OBJECT_NAME = "gene_summaries.jsonl.gz"


class ConfigurationError(RuntimeError):
    """Erreur permanente : la relancer ne peut pas la résoudre."""


def build_client() -> NcbiClient:
    load_dotenv()
    if not os.environ.get("NCBI_EMAIL"):
        raise ConfigurationError(
            "NCBI_EMAIL manquant : renseigner la variable d'environnement (voir README)."
        )
    return NcbiClient(
        email=os.environ["NCBI_EMAIL"], api_key=os.environ.get("NCBI_API_KEY", "")
    )


def ingest_ncbi_gene(
    logical_date: str,
    panel: str,
    genes: list[str],
    client: NcbiClient,
    lake_uri: str | None = None,
) -> str:
    """Dépose les esummary NCBI Gene du panel en Bronze, un enregistrement par gène.

    Un gène que NCBI Gene ne résout pas conserve une entrée à `esummary` vide : le
    verdict qualité appartient à la tâche `check_bronze`, pas à l'ingestion.
    """
    records = [
        {"gene_symbol": gene, "esummary": fetch_gene_info(client, gene)}
        for gene in genes
    ]
    partition = partition_uri(BRONZE, "ncbi_gene", logical_date, panel=panel, lake_uri=lake_uri)
    payload = dumps_gzipped(records)
    put_bytes(f"{partition}/{OBJECT_NAME}", payload)

    finalize_partition(
        partition,
        build_manifest(
            source="ncbi_gene",
            logical_date=logical_date,
            source_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gene",
            source_version=logical_date,
            files={OBJECT_NAME: len(payload)},
            record_count=len(records),
            panel=panel,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les métadonnées NCBI Gene en Bronze.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--genes", required=True, help="symboles séparés par des virgules")
    parser.add_argument("--lake-uri", default=None)
    args = parser.parse_args()
    print(ingest_ncbi_gene(
        args.logical_date, args.panel, args.genes.split(","), build_client(),
        lake_uri=args.lake_uri,
    ))
