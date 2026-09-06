from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ingestion.config import current_lake_uri

S3_SCHEME = "s3://"
FILE_SCHEME = "file://"

SUCCESS_MARKER = "_SUCCESS"
MANIFEST_NAME = "manifest.json"


def layer_uri(layer: str, lake_uri: str | None = None) -> str:
    """URI d'une couche du médaillon.

    Sur MinIO chaque couche est un bucket (`s3://bronze`) ; en local c'est un
    sous-dossier de la racine du lac.
    """
    base = lake_uri if lake_uri is not None else current_lake_uri()
    # "s3://".rstrip("/") vaut "s3:" : c'est la forme "racine S3, la couche est le bucket".
    if base.rstrip("/") == "s3:":
        return f"{S3_SCHEME}{layer}"
    return f"{base.rstrip('/')}/{layer}"


def partition_uri(
    layer: str,
    source: str,
    logical_date: str,
    panel: str | None = None,
    lake_uri: str | None = None,
) -> str:
    """Chemin d'une partition : `<couche>/<source>/dt=<date>[/panel=<panel>]`.

    La date logique est le seul discriminant : rejouer un run réécrit cette
    partition et aucune autre.
    """
    parts = [layer_uri(layer, lake_uri), source, f"dt={logical_date}"]
    if panel:
        parts.append(f"panel={panel}")
    return "/".join(parts)


def _split_s3(uri: str) -> tuple[str, str]:
    bucket, _, key = uri[len(S3_SCHEME):].partition("/")
    return bucket, key


def _local_path(uri: str) -> Path:
    return Path(uri[len(FILE_SCHEME):]) if uri.startswith(FILE_SCHEME) else Path(uri)


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def put_bytes(uri: str, data: bytes, client=None) -> None:
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        (client or _s3_client()).put_object(Bucket=bucket, Key=key, Body=data)
        return
    path = _local_path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def put_file(uri: str, local_path: Path, client=None) -> None:
    """Dépose un fichier depuis le disque, sans le charger en mémoire.

    Indispensable pour le bulk ClinVar (442 Mo).
    """
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        (client or _s3_client()).upload_file(
            Filename=str(local_path), Bucket=bucket, Key=key
        )
        return
    destination = _local_path(uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local_path, destination)


def get_bytes(uri: str, client=None) -> bytes:
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        return (client or _s3_client()).get_object(Bucket=bucket, Key=key)["Body"].read()
    return _local_path(uri).read_bytes()


def open_stream(uri: str, client=None):
    """Ouvre un objet en lecture binaire, sans le matérialiser en mémoire.

    Nécessaire pour le bulk ClinVar : 442 Mo compressés, ~4 Go décompressés, à
    parcourir sur un worker qui ne dispose que de quelques Go.
    """
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        return (client or _s3_client()).get_object(Bucket=bucket, Key=key)["Body"]
    return open(_local_path(uri), "rb")


def exists(uri: str, client=None) -> bool:
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        try:
            (client or _s3_client()).head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return _local_path(uri).exists()


def build_manifest(
    source: str,
    logical_date: str,
    source_url: str,
    source_version: str,
    files: dict[str, int],
    record_count: int,
    panel: str | None = None,
) -> dict:
    """Décrit une partition Bronze de façon auto-portante.

    `source_version` est la version épinglée de la source (mois d'archive ClinVar,
    tag de release HPO), et non l'horodatage local : c'est ce qui rend deux rejeux
    du même `logical_date` comparables.
    """
    return {
        "source": source,
        "logical_date": logical_date,
        "panel": panel,
        "source_url": source_url,
        "source_version": source_version,
        "files": files,
        "record_count": record_count,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }


def finalize_partition(partition: str, manifest: dict, client=None) -> None:
    """Clôt une partition : manifest d'abord, marqueur `_SUCCESS` en dernier.

    L'ordre compte : sur un stockage objet il n'y a pas de renommage atomique, donc
    `_SUCCESS` écrit en dernier est ce qui distingue une partition complète d'une
    partition interrompue.
    """
    payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    put_bytes(f"{partition}/{MANIFEST_NAME}", payload, client=client)
    put_bytes(f"{partition}/{SUCCESS_MARKER}", b"", client=client)


def partition_is_complete(partition: str, client=None) -> bool:
    return exists(f"{partition}/{SUCCESS_MARKER}", client=client)
