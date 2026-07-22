import gzip

import responses
from pathlib import Path

from ingestion.clinvar import (
    CLINVAR_BULK_URL,
    download_variant_summary,
    filter_clinvar,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "clinvar_sample.tsv"


def test_filter_clinvar_keeps_only_target_genes_and_valid_assemblies():
    result = filter_clinvar(FIXTURE, genes=["AP5Z1", "HBB"])
    assert set(result["GeneSymbol"].to_list()) == {"AP5Z1", "HBB"}
    assert result.height == 4


def test_filter_clinvar_drops_grch37_duplicate_assembly_rows():
    result = filter_clinvar(FIXTURE, genes=["AP5Z1"])
    assert result.height == 1
    assert result["Assembly"].to_list() == ["GRCh38"]


def test_filter_clinvar_deduplicates_exact_allele_id_duplicates():
    result = filter_clinvar(FIXTURE, genes=["HBB"])
    allele_ids = result["#AlleleID"].to_list()
    assert len(allele_ids) == len(set(allele_ids))
    assert set(allele_ids) == {"20001", "20002", "20003"}


def test_filter_clinvar_excludes_genes_not_in_scope():
    result = filter_clinvar(FIXTURE, genes=["HBB"])
    assert "PIK3CA" not in result["GeneSymbol"].to_list()


@responses.activate
def test_download_variant_summary_writes_streamed_content(tmp_path):
    body = gzip.compress(b"header\ncontent\n")
    responses.add(responses.GET, CLINVAR_BULK_URL, body=body, status=200)

    destination = tmp_path / "external" / "variant_summary.txt.gz"
    result_path = download_variant_summary(destination)

    assert result_path == destination
    assert destination.read_bytes() == body


@responses.activate
def test_download_variant_summary_reuses_existing_file(tmp_path):
    destination = tmp_path / "external" / "variant_summary.txt.gz"
    destination.parent.mkdir(parents=True)
    existing = gzip.compress(b"already downloaded\n")
    destination.write_bytes(existing)

    result_path = download_variant_summary(destination)

    assert result_path == destination
    assert destination.read_bytes() == existing
    assert len(responses.calls) == 0


@responses.activate
def test_download_variant_summary_force_redownloads_existing_file(tmp_path):
    body = gzip.compress(b"fresh\n")
    responses.add(responses.GET, CLINVAR_BULK_URL, body=body, status=200)

    destination = tmp_path / "external" / "variant_summary.txt.gz"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(gzip.compress(b"stale\n"))

    result_path = download_variant_summary(destination, force=True)

    assert result_path == destination
    assert destination.read_bytes() == body
