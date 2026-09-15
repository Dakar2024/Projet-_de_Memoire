import gzip
import json
from unittest.mock import patch

import pytest
import responses

from ingestion.http_client import NcbiClient, RateLimiter
from ingestion.storage import get_bytes, partition_is_complete
from scripts.ingest_ncbi_gene import ingest_ncbi_gene

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_ingest_ncbi_gene_writes_one_jsonl_record_per_gene(tmp_path):
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["3043"]}}, status=200)
    responses.add(responses.GET, ESUMMARY,
                  json={"result": {"3043": {"name": "HBB"}}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_ncbi_gene("2026-09-01", "sickle", ["HBB"], _client(), lake_uri=lake)

    assert partition == f"{lake}/raw/ncbi_gene/dt=2026-09-01/panel=sickle"
    raw = gzip.decompress(get_bytes(f"{partition}/gene_summaries.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert records == [{"gene_symbol": "HBB", "esummary": {"name": "HBB"}}]
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_ncbi_gene_keeps_unresolved_genes_as_empty_summaries(tmp_path):
    """Un symbole non résolu est une information, pas une erreur : il doit rester
    traçable depuis la partition."""
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_ncbi_gene("2026-09-01", "sickle", ["HBS1L"], _client(), lake_uri=lake)

    raw = gzip.decompress(get_bytes(f"{partition}/gene_summaries.jsonl.gz")).decode()
    assert json.loads(raw.strip()) == {"gene_symbol": "HBS1L", "esummary": {}}


@responses.activate
def test_an_interrupted_replay_leaves_the_partition_incomplete(tmp_path):
    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)
    lake = f"file://{tmp_path}/lake"
    partition = ingest_ncbi_gene("2026-09-01", "sickle", ["HBS1L"], _client(), lake_uri=lake)

    with patch("scripts.ingest_ncbi_gene.put_bytes", side_effect=OSError("connexion perdue en pleine écriture")):
        with pytest.raises(OSError):
            ingest_ncbi_gene("2026-09-01", "sickle", ["HBS1L"], _client(), lake_uri=lake)

    assert partition_is_complete(partition) is False
