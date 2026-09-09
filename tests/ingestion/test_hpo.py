from pathlib import Path

import pytest
import responses

from ingestion.hpo import ReleaseTagResolutionError, release_url_for, resolve_release_tag

FIXTURE = Path(__file__).parent.parent / "fixtures" / "genes_to_phenotype_sample.txt"


def test_parse_genes_to_phenotype_filters_target_genes():
    from ingestion.hpo import parse_genes_to_phenotype

    result = parse_genes_to_phenotype(FIXTURE, genes=["HBB"])
    assert len(result) == 2
    assert all(row["gene_symbol"] == "HBB" for row in result)
    assert result[0] == {
        "gene_symbol": "HBB",
        "hpo_id": "HP:0001878",
        "hpo_name": "Hemolytic anemia",
    }


def test_parse_genes_to_phenotype_excludes_genes_out_of_scope():
    from ingestion.hpo import parse_genes_to_phenotype

    result = parse_genes_to_phenotype(FIXTURE, genes=["HBB"])
    assert "NAT2" not in [row["gene_symbol"] for row in result]


@responses.activate
def test_download_hpo_files_writes_genes_to_phenotype(tmp_path):
    from ingestion.hpo import download_hpo_files, GENES_TO_PHENOTYPE_URL

    responses.add(responses.GET, GENES_TO_PHENOTYPE_URL, body=b"gene-content", status=200)

    result = download_hpo_files(tmp_path)

    assert result == {"genes_to_phenotype": tmp_path / "genes_to_phenotype.txt"}
    assert (tmp_path / "genes_to_phenotype.txt").read_bytes() == b"gene-content"


@responses.activate
def test_fetch_hpo_term_details_returns_details_keyed_by_id():
    from ingestion.hpo import HP_TERMS_URL, fetch_hpo_term_details

    responses.add(
        responses.GET,
        HP_TERMS_URL,
        json=[
            {
                "id": "HP:0001878",
                "name": "Hemolytic anemia",
                "definition": "A type of anemia caused by hemolysis.",
                "synonyms": ["Haemolytic anaemia"],
                "xrefs": ["UMLS:C0002878"],
            }
        ],
        status=200,
    )

    result = fetch_hpo_term_details(["HP:0001878"])

    assert result == {
        "HP:0001878": {
            "definition": "A type of anemia caused by hemolysis.",
            "synonyms": ["Haemolytic anaemia"],
            "xrefs": ["UMLS:C0002878"],
        }
    }
    assert responses.calls[0].request.params["filter"] == "HP:0001878"


@responses.activate
def test_fetch_hpo_term_details_dedupes_ids_before_querying():
    from ingestion.hpo import HP_TERMS_URL, fetch_hpo_term_details

    responses.add(responses.GET, HP_TERMS_URL, json=[], status=200)

    fetch_hpo_term_details(["HP:0001878", "HP:0001878"])

    assert len(responses.calls) == 1
    assert responses.calls[0].request.params["filter"] == "HP:0001878"


@responses.activate
def test_fetch_hpo_term_details_splits_into_batches():
    from ingestion.hpo import HP_TERMS_BATCH_SIZE, HP_TERMS_URL, fetch_hpo_term_details

    ids = [f"HP:{i:07d}" for i in range(HP_TERMS_BATCH_SIZE + 5)]
    responses.add(responses.GET, HP_TERMS_URL, json=[], status=200)
    responses.add(responses.GET, HP_TERMS_URL, json=[], status=200)

    fetch_hpo_term_details(ids)

    assert len(responses.calls) == 2
    first_batch = responses.calls[0].request.params["filter"].split(",")
    second_batch = responses.calls[1].request.params["filter"].split(",")
    assert len(first_batch) == HP_TERMS_BATCH_SIZE
    assert len(second_batch) == 5


def test_fetch_hpo_term_details_makes_no_request_for_empty_list():
    from ingestion.hpo import fetch_hpo_term_details

    assert fetch_hpo_term_details([]) == {}


def test_enrich_hpo_rows_adds_definition_synonyms_xrefs():
    from ingestion.hpo import enrich_hpo_rows

    rows = [{"gene_symbol": "HBB", "hpo_id": "HP:0001878", "hpo_name": "Hemolytic anemia"}]
    term_details = {
        "HP:0001878": {
            "definition": "A type of anemia caused by hemolysis.",
            "synonyms": ["Haemolytic anaemia"],
            "xrefs": ["UMLS:C0002878"],
        }
    }

    result = enrich_hpo_rows(rows, term_details)

    assert result == [
        {
            "gene_symbol": "HBB",
            "hpo_id": "HP:0001878",
            "hpo_name": "Hemolytic anemia",
            "definition": "A type of anemia caused by hemolysis.",
            "synonyms": ["Haemolytic anaemia"],
            "xrefs": ["UMLS:C0002878"],
        }
    ]


def test_enrich_hpo_rows_defaults_to_empty_when_term_missing():
    from ingestion.hpo import enrich_hpo_rows

    rows = [{"gene_symbol": "HBS1L", "hpo_id": "HP:9999999", "hpo_name": "Unknown"}]

    result = enrich_hpo_rows(rows, term_details={})

    assert result[0]["definition"] == ""
    assert result[0]["synonyms"] == []
    assert result[0]["xrefs"] == []


def test_release_url_for_builds_a_tagged_download_url():
    assert release_url_for("v2026-09-01") == (
        "https://github.com/obophenotype/human-phenotype-ontology/releases/"
        "download/v2026-09-01/genes_to_phenotype.txt"
    )


@responses.activate
def test_resolve_release_tag_reads_the_redirect_from_latest():
    responses.add(
        responses.GET,
        "https://github.com/obophenotype/human-phenotype-ontology/releases/latest",
        status=302,
        headers={
            "Location": "https://github.com/obophenotype/human-phenotype-ontology"
            "/releases/tag/v2026-09-01"
        },
    )
    assert resolve_release_tag() == "v2026-09-01"


@responses.activate
def test_resolve_release_tag_reports_a_response_without_a_location_header():
    """429 et 5xx sont déjà retentés par la session : le trou réel est un statut non
    retenté sans redirection, comme une page HTML servie à la place du 302."""
    responses.add(
        responses.GET,
        "https://github.com/obophenotype/human-phenotype-ontology/releases/latest",
        status=200,
        body="<html>page GitHub</html>",
    )
    with pytest.raises(ReleaseTagResolutionError, match="sans en-tête Location"):
        resolve_release_tag()
