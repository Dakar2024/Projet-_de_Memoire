"""Ingestion du fichier HPO genes_to_phenotype dans la couche raw."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.config import DATA_EXTERNAL_DIR, RAW
from ingestion.download import download_to_file
from ingestion.hpo import release_url_for, resolve_release_tag
from ingestion.maintenance import ensure_free_space, purge_old_downloads
from ingestion.storage import (
    begin_partition,
    build_manifest,
    finalize_partition,
    partition_uri,
    put_file,
    read_manifest,
    sha256_file,
)

OBJECT_NAME = "genes_to_phenotype.txt"


def ingest_hpo_files(
    logical_date: str,
    lake_uri: str | None = None,
    cache_dir: Path | None = None,
    release_tag: str | None = None,
) -> str:
    """Dépose `genes_to_phenotype.txt` épinglé sur un tag : explicite, sinon celui du manifest, sinon le dernier."""
    partition = partition_uri(RAW, "hpo", logical_date, lake_uri=lake_uri)
    if not release_tag:
        manifest = read_manifest(partition)
        release_tag = manifest["source_version"] if manifest else resolve_release_tag()
    url = release_url_for(release_tag)
    cache_dir = cache_dir or DATA_EXTERNAL_DIR
    ensure_free_space(cache_dir)
    local = download_to_file(url, cache_dir / f"genes_to_phenotype_{release_tag}.txt")

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
            # Aucune somme publiée pour ce fichier : la nôtre, figée au dépôt, est revérifiée en bronze.
            sha256={OBJECT_NAME: sha256_file(local)},
        ),
    )
    # Purge après finalisation : avant, le fichier local est la seule copie.
    purge_old_downloads(cache_dir)
    return partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dépose les fichiers plats HPO dans la couche raw.")
    parser.add_argument("--logical-date", required=True)
    parser.add_argument("--lake-uri", default=None)
    parser.add_argument("--release-tag", default=None, help="défaut : tag du manifest existant de la partition, sinon /releases/latest")
    args = parser.parse_args()
    print(ingest_hpo_files(args.logical_date, lake_uri=args.lake_uri, release_tag=args.release_tag))
