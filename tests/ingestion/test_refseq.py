import responses

from ingestion.http_client import NcbiClient, RateLimiter

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_fetch_transcripts_returns_one_summary_per_uid():
    from ingestion.refseq import fetch_transcripts

    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": ["2778098787", "2240897268"]}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "2778098787": {"accessionversion": "NM_001432077.1", "slen": 11863}}}, status=200)
    responses.add(responses.GET, ESUMMARY, json={"result": {
        "2240897268": {"accessionversion": "NM_000059.4", "slen": 11986}}}, status=200)

    result = fetch_transcripts(_client(), "BRCA2")

    assert [t["accessionversion"] for t in result] == ["NM_001432077.1", "NM_000059.4"]
    assert result[0]["slen"] == 11863


@responses.activate
def test_fetch_transcripts_returns_empty_list_when_no_transcript():
    from ingestion.refseq import fetch_transcripts

    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)

    assert fetch_transcripts(_client(), "HBS1L") == []


@responses.activate
def test_fetch_transcripts_restricts_to_human_refseq_mrna():
    from ingestion.refseq import fetch_transcripts

    responses.add(responses.GET, ESEARCH,
                  json={"esearchresult": {"idlist": []}}, status=200)

    fetch_transcripts(_client(), "BRCA1")

    sent = responses.calls[0].request.params
    assert sent["db"] == "nuccore"
    assert sent["term"] == (
        "BRCA1[gene] AND human[orgn] AND srcdb_refseq[prop] AND biomol_mrna[prop]"
    )
