import responses

from ingestion.http_client import NcbiClient, RateLimiter


def _client():
    return NcbiClient(
        email="test@example.com",
        rate_limiter=RateLimiter(0.0, sleep_fn=lambda s: None),
    )


@responses.activate
def test_fetch_gene_info_returns_esummary_for_found_gene():
    from ingestion.ncbi_gene import fetch_gene_info

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["3043"]}},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        json={
            "result": {
                "3043": {"name": "HBB", "description": "hemoglobin subunit beta"}
            }
        },
        status=200,
    )
    result = fetch_gene_info(_client(), "HBB")
    assert result["name"] == "HBB"
    assert result["description"] == "hemoglobin subunit beta"


@responses.activate
def test_fetch_gene_info_returns_empty_dict_when_gene_not_found():
    from ingestion.ncbi_gene import fetch_gene_info

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    result = fetch_gene_info(_client(), "HBS1L-MYB")
    assert result == {}


@responses.activate
def test_fetch_gene_info_uses_gene_search_term_format():
    from ingestion.ncbi_gene import fetch_gene_info

    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    fetch_gene_info(_client(), "BRCA1")
    sent_term = responses.calls[0].request.params["term"]
    assert sent_term == "BRCA1[gene] AND human[organism] AND alive[property]"
