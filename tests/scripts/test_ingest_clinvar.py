import json

import responses

from ingestion.storage import get_bytes, partition_is_complete
from scripts.ingest_clinvar import ingest_clinvar

ARCHIVE = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/"
    "variant_summary_2026-09.txt.gz"
)


@responses.activate
def test_ingest_clinvar_deposits_the_bulk_and_finalises_the_partition(tmp_path):
    responses.add(responses.GET, ARCHIVE, body=b"bulk gzippe", status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert partition == f"{lake}/bronze/clinvar/dt=2026-09-01"
    assert get_bytes(f"{partition}/variant_summary.txt.gz") == b"bulk gzippe"
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_clinvar_manifest_pins_the_source_version(tmp_path):
    responses.add(responses.GET, ARCHIVE, body=b"bulk gzippe", status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source"] == "clinvar"
    assert manifest["source_version"] == "2026-09"
    assert manifest["source_url"] == ARCHIVE
    assert manifest["files"] == {"variant_summary.txt.gz": len(b"bulk gzippe")}


@responses.activate
def test_ingest_clinvar_deposits_the_bulk_unfiltered(tmp_path):
    """Bronze est strictement brut : aucun filtrage sur le panel à ce stade."""
    contenu = b"#AlleleID\tGeneSymbol\n1\tINCONNU\n2\tBRCA1\n"
    responses.add(responses.GET, ARCHIVE, body=contenu, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert get_bytes(f"{partition}/variant_summary.txt.gz") == contenu
