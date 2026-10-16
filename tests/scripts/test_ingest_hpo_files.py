import hashlib
import json
from unittest.mock import patch

import pytest
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

    assert partition == f"{lake}/raw/hpo/dt=2026-09-01"
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
    assert manifest["sha256"] == {"genes_to_phenotype.txt": hashlib.sha256(b"contenu").hexdigest()}


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


@responses.activate
def test_an_interrupted_replay_leaves_the_partition_incomplete(tmp_path):
    responses.add(responses.GET, RELEASE, body=b"contenu", status=200)
    lake = f"file://{tmp_path}/lake"
    kwargs = dict(lake_uri=lake, cache_dir=tmp_path / "cache", release_tag="v2026-09-01")
    partition = ingest_hpo_files("2026-09-01", **kwargs)

    with patch("scripts.ingest_hpo_files.put_file", side_effect=OSError("connexion perdue en pleine écriture")):
        with pytest.raises(OSError):
            ingest_hpo_files("2026-09-01", **kwargs)

    assert partition_is_complete(partition) is False


def _refuse_network():
    raise AssertionError("/releases/latest ne doit pas être interrogé")


@responses.activate
def test_a_replay_reuses_the_release_tag_of_the_existing_manifest(tmp_path):
    """Rejouer un mois passé ne doit pas écraser sa partition avec la release courante :
    le tag déjà inscrit au manifest prime sur `/releases/latest`."""
    responses.add(responses.GET, RELEASE, body=b"contenu", status=200)
    lake = f"file://{tmp_path}/lake"
    ingest_hpo_files(
        "2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache",
        release_tag="v2026-09-01",
    )

    with patch("scripts.ingest_hpo_files.resolve_release_tag", side_effect=_refuse_network):
        partition = ingest_hpo_files("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source_version"] == "v2026-09-01"


@responses.activate
def test_a_first_run_resolves_the_latest_release(tmp_path):
    responses.add(responses.GET, RELEASE, body=b"contenu", status=200)
    lake = f"file://{tmp_path}/lake"

    with patch(
        "scripts.ingest_hpo_files.resolve_release_tag", return_value="v2026-09-01"
    ) as espion:
        partition = ingest_hpo_files("2026-09-01", lake_uri=lake, cache_dir=tmp_path / "cache")

    assert espion.call_count == 1
    assert json.loads(get_bytes(f"{partition}/manifest.json"))["source_version"] == "v2026-09-01"


@responses.activate
def test_an_explicit_release_tag_overrides_the_existing_manifest(tmp_path):
    other = RELEASE.replace("v2026-09-01", "v2026-10-01")
    responses.add(responses.GET, RELEASE, body=b"contenu", status=200)
    responses.add(responses.GET, other, body=b"autre", status=200)
    lake = f"file://{tmp_path}/lake"
    cache = tmp_path / "cache"
    ingest_hpo_files("2026-09-01", lake_uri=lake, cache_dir=cache, release_tag="v2026-09-01")

    with patch("scripts.ingest_hpo_files.resolve_release_tag", side_effect=_refuse_network):
        partition = ingest_hpo_files(
            "2026-09-01", lake_uri=lake, cache_dir=cache, release_tag="v2026-10-01"
        )

    assert json.loads(get_bytes(f"{partition}/manifest.json"))["source_version"] == "v2026-10-01"
