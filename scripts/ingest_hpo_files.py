from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import DATA_EXTERNAL_DIR, RAW
from ingestion.download import download_to_file
from ingestion.hpo import release_url_for, resolve_release_tag
from ingestion.storage import (
    begin_partition,
    build_manifest,
    finalize_partition,
    partition_uri,
    put_file,
)

OBJECT_NAME = "genes_to_phenotype.txt"


def ingest_hpo_files(
    logical_date: str,
    lake_uri: str | None = None,
    cache_dir: Path | None = None,
    release_tag: str | None = None,
) -> str:
    """Dépose `genes_to_phenotype.txt` dans la couche raw, épinglé sur un tag de release.

    Le tag résolu est inscrit au manifest : c'est lui, et non la date du run, qui
    identifie la version de la source.
    """
    release_tag = release_tag or resolve_release_tag()
    url = release_url_for(release_tag)
    cache_dir = cache_dir or DATA_EXTERNAL_DIR
    local = download_to_file(url, cache_dir / f"genes_to_phenotype_{release_tag}.txt")

    partition = partition_uri(RAW, "hpo", logical_date, lake_uri=lake_uri)
    begin_partition(partition)
    put_file(f"{partition}/{OBJECT_NAME}", local)

    finalize_partition(
        partition,
        build_manifest(
            source="hpo",
            logical_date=logical_date,
            source_url=url,
            source_version=release_tag,
            files={OBJECT_NAME: local.stat().st_size},
            record_count=1,
        ),
    )
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les fichiers plats HPO dans la couche raw.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--lake-uri", default=None)
    parser.add_argument("--release-tag", default=None, help="défaut : résolu depuis /releases/latest")
    args = parser.parse_args()
    print(ingest_hpo_files(args.logical_date, lake_uri=args.lake_uri, release_tag=args.release_tag))
