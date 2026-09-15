import gzip
import json

import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.storage import get_bytes, partition_is_complete
from scripts.ingest_refseq import ingest_refseq

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


def _records(partition):
    raw = gzip.decompress(get_bytes(f"{partition}/transcripts.jsonl.gz")).decode()
    return [json.loads(line) for line in raw.splitlines()]


@responses.activate
def test_ingest_refseq_writes_one_record_per_gene(tmp_path):
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["2778098787"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "2778098787": {"accessionversion": "NM_001432077.1", "slen": 11863}}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_refseq("2026-09-01", "brca", ["BRCA2"], _client(), lake_uri=lake)

    assert partition == f"{lake}/raw/refseq/dt=2026-09-01/panel=brca"
    assert _records(partition) == [{
        "gene_symbol": "BRCA2",
        "transcripts": [{"accessionversion": "NM_001432077.1", "slen": 11863}],
    }]
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_refseq_keeps_genes_without_transcripts(tmp_path):
    """Un gène sans transcrit garde son entrée : un symbole en échec doit rester
    traçable depuis la partition, le verdict appartient à `check_raw`."""
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_refseq("2026-09-01", "brca", ["INCONNU"], _client(), lake_uri=lake)

    assert _records(partition) == [{"gene_symbol": "INCONNU", "transcripts": []}]


@responses.activate
def test_ingest_refseq_manifest_records_the_panel_and_count(tmp_path):
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_refseq(
        "2026-09-01", "sickle", ["HBB", "HBS1L"], _client(), lake_uri=lake
    )

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source"] == "refseq"
    assert manifest["panel"] == "sickle"
    assert manifest["record_count"] == 2
