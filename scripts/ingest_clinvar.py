from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.clinvar import archive_url_for, archive_version_for
from ingestion.config import DATA_EXTERNAL_DIR, RAW
from ingestion.download import download_to_file
from ingestion.storage import (
    build_manifest,
    finalize_partition,
    partition_uri,
    put_file,
)

OBJECT_NAME = "variant_summary.txt.gz"


def ingest_clinvar(
    logical_date: str, lake_uri: str | None = None, cache_dir: Path | None = None
) -> str:
    """Dépose le bulk ClinVar du mois de `logical_date` dans la couche raw, sans le filtrer.

    Le fichier est d'abord téléchargé sur disque puis téléversé en flux : à 442 Mo,
    il ne doit jamais transiter par la mémoire du worker Airflow.
    """
    url = archive_url_for(logical_date)
    cache_dir = cache_dir or DATA_EXTERNAL_DIR
    local = download_to_file(url, cache_dir / f"variant_summary_{archive_version_for(logical_date)}.txt.gz")

    partition = partition_uri(RAW, "clinvar", logical_date, lake_uri=lake_uri)
    put_file(f"{partition}/{OBJECT_NAME}", local)

    finalize_partition(
        partition,
        build_manifest(
            source="clinvar",
            logical_date=logical_date,
            source_url=url,
            source_version=archive_version_for(logical_date),
            files={OBJECT_NAME: local.stat().st_size},
            record_count=1,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose le bulk ClinVar dans la couche raw.")
    parser.add_argument("--logical-date", required=True, help="date logique du run (YYYY-MM-DD)")
    parser.add_argument("--lake-uri", default=None, help="racine du lac (défaut : LAKE_URI)")
    args = parser.parse_args()
    print(ingest_clinvar(args.logical_date, lake_uri=args.lake_uri))
