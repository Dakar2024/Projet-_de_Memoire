import gzip
import json

import responses

from ingestion.storage import get_bytes, partition_is_complete, put_bytes
from scripts.ingest_hpo_terms import ingest_hpo_terms

HP_TERMS = "https://ontology.jax.org/api/hp/terms"

FLAT = (
    "ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n"
    "3043\tHBB\tHP:0001903\tAnemia\n"
    "9999\tAUTRE\tHP:0000118\tPhenotypic abnormality\n"
)


def _seed_flat_file(tmp_path) -> str:
    lake = f"file://{tmp_path}/lake"
    put_bytes(f"{lake}/raw/hpo/dt=2026-09-01/genes_to_phenotype.txt", FLAT.encode())
    return lake


@responses.activate
def test_ingest_hpo_terms_enriches_only_the_panel_genes(tmp_path):
    """Le fichier plat est partagé entre panels : seuls les termes des gènes du
    panel demandé doivent être enrichis et déposés."""
    lake = _seed_flat_file(tmp_path)
    responses.add(responses.GET, HP_TERMS, json=[
        {"id": "HP:0001903", "definition": "A reduction in erythrocytes.",
         "synonyms": ["Low blood count"], "xrefs": ["UMLS:C0002871"]}], status=200)

    partition = ingest_hpo_terms("2026-09-01", "sickle", ["HBB"], lake_uri=lake)

    assert partition == f"{lake}/raw/hpo_terms/dt=2026-09-01/panel=sickle"
    raw = gzip.decompress(get_bytes(f"{partition}/hpo_terms.jsonl.gz")).decode()
    records = [json.loads(line) for line in raw.splitlines()]
    assert [r["hpo_id"] for r in records] == ["HP:0001903"]
    assert records[0]["details"]["definition"] == "A reduction in erythrocytes."
    assert partition_is_complete(partition) is True


@responses.activate
def test_ingest_hpo_terms_manifest_records_the_panel(tmp_path):
    lake = _seed_flat_file(tmp_path)
    responses.add(responses.GET, HP_TERMS, json=[], status=200)

    partition = ingest_hpo_terms("2026-09-01", "sickle", ["HBB"], lake_uri=lake)

    manifest = json.loads(get_bytes(f"{partition}/manifest.json"))
    assert manifest["source"] == "hpo_terms"
    assert manifest["panel"] == "sickle"
