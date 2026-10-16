"""Entrées-sorties du lac médaillon (`file://` ou `s3://`) et protocole de partition."""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from botocore.exceptions import ClientError

from ingestion.config import LOGICAL_DATE_PATTERN, current_lake_uri

S3_SCHEME = "s3://"
FILE_SCHEME = "file://"

SUCCESS_MARKER = "_SUCCESS"
MANIFEST_NAME = "manifest.json"

# Noms de source et de panel : minuscules, chiffres, `_` ; ni `/`, ni `..`, ni vide (I1).
_PATH_COMPONENT = re.compile(r"[a-z][a-z0-9_]*")


def layer_uri(layer: str, lake_uri: str | None = None) -> str:
    """Renvoie l'URI d'une couche : un bucket sur MinIO, un sous-dossier en local."""
    base = lake_uri if lake_uri is not None else current_lake_uri()
    # Racine `s3://` : la couche est le bucket.
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
    """Renvoie le chemin d'une partition : `<couche>/<source>/dt=<date>[/panel=<panel>]`, composants validés."""
    _check_partition_components(source, logical_date, panel)
    parts = [layer_uri(layer, lake_uri), source, f"dt={logical_date}"]
    if panel:
        parts.append(f"panel={panel}")
    return "/".join(parts)


def _check_partition_components(source: str, logical_date: str, panel: str | None) -> None:
    """Refuse un composant qui sortirait de la partition (`..`, `/`, saut de ligne) ou mal formé."""
    # `fullmatch` et non `match` : `$` accepte un saut de ligne final.
    if not _PATH_COMPONENT.fullmatch(source):
        raise ValueError(f"source de partition invalide : {source!r}")
    if not LOGICAL_DATE_PATTERN.fullmatch(logical_date):
        raise ValueError(f"date de partition invalide : {logical_date!r} — format attendu YYYY-MM-DD")
    if panel is not None and not _PATH_COMPONENT.fullmatch(panel):
        raise ValueError(f"panel de partition invalide : {panel!r}")


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
    """Écrit des octets à `uri`."""
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        (client or _s3_client()).put_object(Bucket=bucket, Key=key, Body=data)
        return
    path = _local_path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def put_file(uri: str, local_path: Path, client=None) -> None:
    """Dépose un fichier local sans le charger en mémoire."""
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
    """Lit un objet entier."""
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        return (client or _s3_client()).get_object(Bucket=bucket, Key=key)["Body"].read()
    return _local_path(uri).read_bytes()


def open_stream(uri: str, client=None):
    """Ouvre un objet en flux binaire, sans le charger en mémoire."""
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        return (client or _s3_client()).get_object(Bucket=bucket, Key=key)["Body"]
    return open(_local_path(uri), "rb")


def storage_options(uri: str) -> dict[str, str] | None:
    """Renvoie les options S3 pour Polars/delta-rs, ou `None` en local."""
    if not uri.startswith(S3_SCHEME):
        return None
    return {
        "aws_endpoint_url": os.environ.get("AWS_ENDPOINT_URL", ""),
        "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
        "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", ""),
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        "aws_allow_http": "true",
    }


def scan_parquet(uri: str) -> pl.LazyFrame:
    """Lit un Parquet en lazy, pour que filtres et projections soient poussés à la lecture."""
    if uri.startswith(S3_SCHEME):
        return pl.scan_parquet(uri, storage_options=storage_options(uri))
    return pl.scan_parquet(_local_path(uri))


def exists(uri: str, client=None) -> bool:
    """Teste la présence d'un objet ; seul un 404 vaut absence, toute autre erreur remonte."""
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        try:
            (client or _s3_client()).head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                return False
            raise
    return _local_path(uri).exists()


def delete(uri: str, client=None) -> None:
    """Supprime un objet ; un objet absent n'est pas une erreur."""
    if uri.startswith(S3_SCHEME):
        bucket, key = _split_s3(uri)
        (client or _s3_client()).delete_object(Bucket=bucket, Key=key)
        return
    _local_path(uri).unlink(missing_ok=True)


def build_manifest(
    source: str,
    logical_date: str,
    source_url: str,
    source_version: str,
    files: dict[str, int],
    record_count: int,
    panel: str | None = None,
) -> dict:
    """Construit le manifest d'une partition, avec la version épinglée de la source."""
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


def begin_partition(partition: str, client=None) -> None:
    """Retire le `_SUCCESS` d'une partition avant de la réécrire (begin → données → manifest → `_SUCCESS`)."""
    delete(f"{partition}/{SUCCESS_MARKER}", client=client)


def finalize_partition(partition: str, manifest: dict, client=None) -> None:
    """Clôt une partition : manifest d'abord, `_SUCCESS` en dernier (pas de renommage atomique en S3)."""
    payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    put_bytes(f"{partition}/{MANIFEST_NAME}", payload, client=client)
    put_bytes(f"{partition}/{SUCCESS_MARKER}", b"", client=client)


def read_manifest(partition: str, client=None) -> dict | None:
    """Renvoie le manifest d'une partition, ou None."""
    uri = f"{partition}/{MANIFEST_NAME}"
    if not exists(uri, client=client):
        return None
    return json.loads(get_bytes(uri, client=client))


def partition_is_complete(partition: str, client=None) -> bool:
    """Indique si la partition porte son marqueur `_SUCCESS`."""
    return exists(f"{partition}/{SUCCESS_MARKER}", client=client)


class IncompletePartitionError(RuntimeError):
    """Une ou plusieurs partitions sont incomplètes ou vides."""


def assert_partitions_complete(partitions: list[str], client=None) -> None:
    """Lève si une partition est incomplète ou vide, en les nommant toutes."""
    if not partitions:
        raise IncompletePartitionError("aucune partition à contrôler")
    failures = []
    for partition in partitions:
        if not partition_is_complete(partition, client=client):
            failures.append(f"{partition} (_SUCCESS absent)")
            continue
        manifest = read_manifest(partition, client=client) or {}
        record_count = manifest.get("record_count")
        if not isinstance(record_count, int) or record_count <= 0:
            failures.append(f"{partition} (record_count nul)")
    if failures:
        raise IncompletePartitionError(
            "partitions incomplètes ou vides : " + ", ".join(failures)
        )
