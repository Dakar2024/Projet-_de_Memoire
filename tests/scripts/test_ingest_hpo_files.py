import json

import responses

from ingestion.storage import get_bytes, partition_is_complete
from scripts.ingest_hpo_files import ingest_hpo_files

RELEASE = (
    "https://github.com/obophenotype/human-phenotype-ontology/releases/"
    "download/v2026-09-01/genes_to_phenotype.txt"
)


@responses.activate
def test_ingest_hpo_files_deposits_the_flat_file_and_finalises_the_partition(tmp_path):
    responses.add(responses.GET, RELEASE, body=b"ncbi_gene_id\tgene_symbol\n", status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_hpo_files(
        "2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache",
        release_tag="v2026-09-01",
    )

    assert partition == f"{lake}/bronze/hpo/dt=2026-09-01"
    assert get_bytes(f"{partition}/genes_to_phenotype.txt") == b"ncbi_gene_id\tgene_symbol\n"
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_hpo_files_manifest_pins_the_release_tag(tmp_path):
    responses.add(responses.GET, RELEASE, body=b"contenu", status=200)
    lake = f"file://{tmp_path}/lake"

    partition = ingest_hpo_files(
        "2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache",
        release_tag="v2026-09-01",
    )

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source"] == "hpo"
    assert manifest["source_version"] == "v2026-09-01"
    assert manifest["source_url"] == RELEASE
    assert manifest["files"] == {"genes_to_phenotype.txt": len(b"contenu")}


@responses.activate
def test_ingest_hpo_files_does_not_resolve_the_tag_when_one_is_given(tmp_path):
    """Un `release_tag` explicite doit éviter tout appel réseau à GitHub : c'est ce
    qui rend un rejeu reproductible et les tests hors-ligne."""
    responses.add(responses.GET, RELEASE, body=b"contenu", status=200)

    ingest_hpo_files(
        "2026-09-01", lake_uri=f"file://{tmp_path}/lake",
        cache_dir=tmp_path / "cache", release_tag="v2026-09-01",
    )

    appelees = {call.request.url for call in responses.calls}
    assert appelees == {RELEASE}
