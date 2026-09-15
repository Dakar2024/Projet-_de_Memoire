import io
import json

import pytest
from botocore.exceptions import ClientError

from ingestion.storage import (
    build_manifest,
    exists,
    finalize_partition,
    get_bytes,
    layer_uri,
    open_stream,
    partition_is_complete,
    partition_uri,
    put_bytes,
    put_file,
)


def _client_error(status: int, code: str) -> ClientError:
    """Erreur boto3 réaliste : le code de statut est ce que `exists()` inspecte."""
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "HeadObject",
    )


class FakeS3:
    """Client S3 minimal : le projet injecte déjà ses clients HTTP, on garde ce style."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def upload_file(self, Filename, Bucket, Key):
        with open(Filename, "rb") as fh:
            self.objects[(Bucket, Key)] = fh.read()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise _client_error(404, "404")
        return {"Body": _Body(self.objects[(Bucket, Key)])}


    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise _client_error(404, "404")
        return {"ContentLength": len(self.objects[(Bucket, Key)])}


class _Body:
    """Imite `StreamingBody` de boto3 : lecture par tranches et context manager."""

    def __init__(self, data):
        self._buffer = io.BytesIO(data)

    def read(self, size=-1):
        return self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._buffer.close()
        return False


def test_layer_uri_joins_a_local_directory():
    assert layer_uri("raw", "file:///tmp/lac/") == "file:///tmp/lac/raw"


def test_layer_uri_treats_each_layer_as_a_bucket_on_s3():
    assert layer_uri("raw", "s3://") == "s3://raw"


def test_partition_uri_without_panel():
    uri = partition_uri("raw", "clinvar", "2026-09-01", lake_uri="s3://")
    assert uri == "s3://raw/clinvar/dt=2026-09-01"


def test_partition_uri_with_panel():
    uri = partition_uri("raw", "medgen", "2026-09-01", panel="brca", lake_uri="s3://")
    assert uri == "s3://raw/medgen/dt=2026-09-01/panel=brca"


def test_put_and_get_bytes_on_local_filesystem(tmp_path):
    uri = f"file://{tmp_path}/raw/clinvar/dt=2026-09-01/data.txt"
    put_bytes(uri, b"contenu")
    assert get_bytes(uri) == b"contenu"
    assert exists(uri) is True


def test_put_and_get_bytes_on_s3():
    client = FakeS3()
    uri = "s3://raw/clinvar/dt=2026-09-01/data.txt"
    put_bytes(uri, b"contenu", client=client)
    assert client.objects[("raw", "clinvar/dt=2026-09-01/data.txt")] == b"contenu"
    assert get_bytes(uri, client=client) == b"contenu"


def test_put_file_streams_from_disk(tmp_path):
    """Le bulk ClinVar fait 442 Mo : il ne doit jamais transiter par la mémoire."""
    source = tmp_path / "bulk.gz"
    source.write_bytes(b"donnees volumineuses")
    client = FakeS3()

    put_file("s3://raw/clinvar/dt=2026-09-01/bulk.gz", source, client=client)

    assert client.objects[("raw", "clinvar/dt=2026-09-01/bulk.gz")] == b"donnees volumineuses"


def test_exists_is_false_for_missing_object(tmp_path):
    assert exists(f"file://{tmp_path}/absent.txt") is False


def test_open_stream_reads_without_materialising_the_whole_object(tmp_path):
    """Le bulk ClinVar fait 442 Mo compressés (~4 Go décompressés) : les
    consommateurs doivent pouvoir le parcourir sans le charger en mémoire."""
    uri = f"file://{tmp_path}/raw/clinvar/dt=2026-09-01/data.bin"
    put_bytes(uri, b"premier|second")

    with open_stream(uri) as stream:
        assert stream.read(7) == b"premier"
        assert stream.read() == b"|second"


def test_open_stream_reads_from_s3():
    client = FakeS3()
    uri = "s3://raw/clinvar/dt=2026-09-01/data.bin"
    put_bytes(uri, b"flux s3", client=client)

    with open_stream(uri, client=client) as stream:
        assert stream.read() == b"flux s3"


def test_build_manifest_records_source_version_and_sizes():
    manifest = build_manifest(
        source="clinvar",
        logical_date="2026-09-01",
        source_url="https://example.org/variant_summary_2026-09.txt.gz",
        source_version="2026-09",
        files={"variant_summary.txt.gz": 442495433},
        record_count=1,
    )
    assert manifest["source"] == "clinvar"
    assert manifest["logical_date"] == "2026-09-01"
    assert manifest["source_version"] == "2026-09"
    assert manifest["files"] == {"variant_summary.txt.gz": 442495433}
    assert manifest["record_count"] == 1
    assert manifest["panel"] is None
    assert manifest["written_at"].endswith("+00:00")


def test_finalize_partition_writes_manifest_then_success_marker(tmp_path):
    partition = f"file://{tmp_path}/raw/clinvar/dt=2026-09-01"
    manifest = build_manifest(
        source="clinvar", logical_date="2026-09-01", source_url="u",
        source_version="v", files={}, record_count=0,
    )

    finalize_partition(partition, manifest)

    written = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert written["source"] == "clinvar"
    assert exists(f"{partition}/_SUCCESS") is True


def test_partition_is_complete_only_after_finalize(tmp_path):
    partition = f"file://{tmp_path}/raw/hpo/dt=2026-09-01"
    put_bytes(f"{partition}/genes_to_phenotype.txt.gz", b"x")

    assert partition_is_complete(partition) is False

    finalize_partition(partition, build_manifest(
        source="hpo", logical_date="2026-09-01", source_url="u",
        source_version="v", files={}, record_count=0,
    ))

    assert partition_is_complete(partition) is True


def test_exists_propagates_a_permission_error_instead_of_reporting_absence():
    """Un 403 n'est pas une absence : le confondre ferait lire une partition
    complète comme incomplète, et `check_raw` échouerait pour la mauvaise raison."""
    class Forbidden(FakeS3):
        def head_object(self, Bucket, Key):
            raise _client_error(403, "403")

    with pytest.raises(ClientError):
        exists("s3://raw/clinvar/dt=2026-09-01/data.txt", client=Forbidden())


def test_exists_propagates_a_connection_failure():
    """Une panne réseau ne lève pas ClientError du tout : elle doit remonter."""
    from botocore.exceptions import EndpointConnectionError

    class Unreachable(FakeS3):
        def head_object(self, Bucket, Key):
            raise EndpointConnectionError(endpoint_url="http://minio:9000")

    with pytest.raises(EndpointConnectionError):
        exists("s3://raw/clinvar/dt=2026-09-01/data.txt", client=Unreachable())


@pytest.mark.integration
def test_storage_round_trip_against_a_real_minio():
    """Le client factice valide la logique ; ce test valide le contrat S3 réel.

    Exclu de la passe rapide (`addopts = -m "not integration"`). Prérequis :
    un MinIO joignable et les variables AWS_* renseignées, avec un bucket `raw`.
    """
    partition = partition_uri("raw", "test_integration", "2026-09-01", lake_uri="s3://")
    put_bytes(f"{partition}/data.txt", b"aller-retour")

    assert get_bytes(f"{partition}/data.txt") == b"aller-retour"

    finalize_partition(partition, build_manifest(
        source="test_integration", logical_date="2026-09-01", source_url="u",
        source_version="v", files={"data.txt": 12}, record_count=1,
    ))
    assert partition_is_complete(partition) is True
