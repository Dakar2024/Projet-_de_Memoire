from pathlib import Path

import responses

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
