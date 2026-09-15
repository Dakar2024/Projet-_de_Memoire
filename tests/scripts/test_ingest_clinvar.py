import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from ingestion.storage import get_bytes, partition_is_complete, put_file
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

    assert partition == f"{lake}/raw/clinvar/dt=2026-09-01"
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
    """La couche raw est strictement brute : aucun filtrage sur le panel à ce stade."""
    contenu = b"#AlleleID\tGeneSymbol\n1\tINCONNU\n2\tBRCA1\n"
    responses.add(responses.GET, ARCHIVE, body=contenu, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert get_bytes(f"{partition}/variant_summary.txt.gz") == contenu


@responses.activate
def test_ingest_clinvar_uploads_the_bulk_from_disk_not_from_memory(tmp_path):
    """Le bulk fait 442 Mo : il doit être téléversé depuis le disque. Sans ce test,
    un passage de `put_file` à `put_bytes` passerait inaperçu — sur un fichier de
    test de 11 octets, les deux produisent un résultat identique."""
    responses.add(responses.GET, ARCHIVE, body=b"bulk gzippe", status=200)
    lake = f"file://{tmp_path}/lake"

    with patch("scripts.ingest_clinvar.put_file", wraps=put_file) as espion:
        ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert espion.call_count == 1
    _uri, source = espion.call_args.args
    assert isinstance(source, Path), "le bulk doit être téléversé depuis un chemin"


@responses.activate
def test_an_interrupted_replay_leaves_the_partition_incomplete(tmp_path):
    """Un rejeu qui échoue en cours d'écriture ne doit pas laisser l'ancien `_SUCCESS`
    faire passer des données à moitié réécrites pour une partition complète."""
    responses.add(responses.GET, ARCHIVE, body=b"bulk gzippe", status=200)
    lake = f"file://{tmp_path}/lake"
    partition = ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    with patch("scripts.ingest_clinvar.put_file", side_effect=OSError("connexion perdue en pleine écriture")):
        with pytest.raises(OSError):
            ingest_clinvar("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert partition_is_complete(partition) is False
