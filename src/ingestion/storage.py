from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from botocore.exceptions import ClientError

from ingestion.config import current_lake_uri

S3_SCHEME = "s3://"
FILE_SCHEME = "file://"

SUCCESS_MARKER = "_SUCCESS"
MANIFEST_NAME = "manifest.json"


def layer_uri(layer: str, lake_uri: str | None = None) -> str:
    """URI d'une couche du médaillon.

    Sur MinIO chaque couche est un bucket (`s3://raw`) ; en local c'est un
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


def storage_options(uri: str) -> dict[str, str] | None:
    """Options de connexion à passer à Polars/delta-rs (`scan_parquet`, `read_delta`,
    `write_delta`, `DeltaTable`) : ils ne lisent pas la configuration boto3 du process.
    En s3://, identifiants et endpoint viennent des mêmes variables que `_s3_client` ;
    `None` en local. Aucun verrou n'est configuré : delta-rs 1.6 écrit sur MinIO sans
    (vérifié en run réel), et le pool Airflow `SILVER_WRITE_POOL` sérialise déjà les
    écrivains Silver."""
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
    """Lit un Parquet en lazy : le filtre et la projection de l'appelant sont poussés
    par Polars au moment du `.collect()`, sans matérialiser toute la partition en
    mémoire au préalable — indispensable pour le bronze ClinVar (bulk non filtré, non
    dédoublonné à ce stade, cf. `raw_to_bronze`)."""
    if uri.startswith(S3_SCHEME):
        return pl.scan_parquet(uri, storage_options=storage_options(uri))
    return pl.scan_parquet(_local_path(uri))


def exists(uri: str, client=None) -> bool:
    """Teste la présence d'un objet, sans masquer les pannes.

    Seul un 404 signifie « absent ». Un 403 (identifiants invalides) ou une panne
    réseau doivent remonter : les confondre avec une absence ferait lire une
    partition complète comme incomplète, exactement le mode de défaillance que ce
    module existe pour empêcher.
    """
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
    """Supprime un objet ; une absence n'est pas une erreur (comme `delete_object` S3)."""
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
    """Décrit une partition de façon auto-portante.

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


def begin_partition(partition: str, client=None) -> None:
    """Ouvre l'écriture d'une partition : retire son marqueur `_SUCCESS` éventuel.

    Pendant de `finalize_partition`. Un rejeu réécrit la partition en place : sans
    ce retrait, un rejeu interrompu laisserait l'ancien `_SUCCESS` à côté de données
    à moitié réécrites, et la partition passerait pour complète. Le protocole est
    donc begin → données → manifest → `_SUCCESS`.
    """
    delete(f"{partition}/{SUCCESS_MARKER}", client=client)


def finalize_partition(partition: str, manifest: dict, client=None) -> None:
    """Clôt une partition : manifest d'abord, marqueur `_SUCCESS` en dernier.

    L'ordre compte : sur un stockage objet il n'y a pas de renommage atomique, donc
    `_SUCCESS` écrit en dernier est ce qui distingue une partition complète d'une
    partition interrompue.
    """
    payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    put_bytes(f"{partition}/{MANIFEST_NAME}", payload, client=client)
    put_bytes(f"{partition}/{SUCCESS_MARKER}", b"", client=client)


def read_manifest(partition: str, client=None) -> dict | None:
    """Manifest d'une partition, ou None si elle n'en a pas."""
    uri = f"{partition}/{MANIFEST_NAME}"
    if not exists(uri, client=client):
        return None
    return json.loads(get_bytes(uri, client=client))


def partition_is_complete(partition: str, client=None) -> bool:
    return exists(f"{partition}/{SUCCESS_MARKER}", client=client)


class IncompletePartitionError(RuntimeError):
    """Une ou plusieurs partitions sont incomplètes ou vides."""


def assert_partitions_complete(partitions: list[str], client=None) -> None:
    """Lève si une partition est incomplète ou vide, en les nommant toutes.

    Utilisée par les tâches de contrôle des DAGs pour bloquer la propagation vers la
    couche suivante. Toutes les partitions sont vérifiées avant de lever.

    Contrôle de complétude et de non-vacuité seulement : `_SUCCESS` présent et
    `record_count` du manifest strictement positif. Les contrôles de contenu
    (colonnes attendues, gènes résolus) relèvent de `check_bronze`.
    """
    if not partitions:
        # Une liste vide ferait réussir le contrôle sans rien vérifier.
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
