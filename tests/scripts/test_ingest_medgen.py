import gzip
import json
from unittest.mock import patch

import pytest
import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.storage import get_bytes, open_stream, partition_is_complete, put_bytes
from scripts.ingest_medgen import cuis_from_raw_clinvar, ingest_medgen

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

BULK = (
    "#AlleleID\tGeneSymbol\tPhenotypeIDS\n"
    "1\tHBB\tMedGen:C0002895,OMIM:603903\n"
    "2\tINCONNU\tMedGen:C9999999\n"
    "3\tHBB\tMedGen:C0002895\n"
)


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


def _seed_raw_clinvar(tmp_path) -> str:
    partition = f"file://{tmp_path}/lake/raw/clinvar/dt=2026-09-01"
    put_bytes(f"{partition}/variant_summary.txt.gz", gzip.compress(BULK.encode()))
    return partition


def _mock_one_concept():
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["287"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "287": {"conceptid": "C0002895", "conceptmeta": "<OMIM><MIM>603903</MIM></OMIM>"}
    }}, status=200)


def test_cuis_from_raw_clinvar_keeps_only_panel_genes(tmp_path):
    """La lecture du bulk pilote les appels d'API ; rien n'est persisté."""
    partition = _seed_raw_clinvar(tmp_path)

    assert cuis_from_raw_clinvar(partition, ["HBB"]) == ["C0002895"]


def test_cuis_from_raw_clinvar_deduplicates_in_order(tmp_path):
    partition = _seed_raw_clinvar(tmp_path)

    assert cuis_from_raw_clinvar(partition, ["HBB", "INCONNU"]) == [
        "C0002895",
        "C9999999",
    ]


def test_cuis_from_raw_clinvar_streams_the_bulk(tmp_path):
    """Le bulk fait ~4 Go décompressés : il doit être lu par `open_stream`. Sur un
    fichier de test de quelques octets, un chargement complet en mémoire donnerait le
    même résultat — seule la vérification de l'appel attrape cette régression."""
    partition = _seed_raw_clinvar(tmp_path)

    with patch("scripts.ingest_medgen.open_stream", wraps=open_stream) as espion:
        assert cuis_from_raw_clinvar(partition, ["HBB"]) == ["C0002895"]

    assert espion.call_count == 1
    assert espion.call_args.args[0] == f"{partition}/variant_summary.txt.gz"


@responses.activate
def test_ingest_medgen_writes_one_record_per_cui_in_raw(tmp_path):
    _seed_raw_clinvar(tmp_path)
    _mock_one_concept()
    lake = f"file://{tmp_path}/lake"

    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    assert partition == f"{lake}/raw/medgen/dt=2026-09-01/panel=sickle"
    raw = gzip.decompress(get_bytes(f"{partition}/concepts.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["cui"] for r in records] == ["C0002895"]
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_medgen_keeps_the_conceptmeta_xml_unparsed(tmp_path):
    """La couche raw est brute : l'aplatissement du XML appartient au Silver."""
    _seed_raw_clinvar(tmp_path)
    _mock_one_concept()
    lake = f"file://{tmp_path}/lake"

    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    record = json.loads(
        gzip.decompress(get_bytes(f"{partition}/concepts.jsonl.gz")).decode().splitlines()[0]
    )
    assert "mim_number" not in record["esummary"]
    assert record["esummary"]["conceptmeta"] == "<OMIM><MIM>603903</MIM></OMIM>"


@responses.activate
def test_an_interrupted_replay_leaves_the_partition_incomplete(tmp_path):
    _seed_raw_clinvar(tmp_path)
    _mock_one_concept()
    lake = f"file://{tmp_path}/lake"
    partition = ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    with (
        patch("scripts.ingest_medgen.put_bytes", side_effect=OSError("connexion perdue en pleine écriture")),
        pytest.raises(OSError),
    ):
        ingest_medgen("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    assert partition_is_complete(partition) is False
