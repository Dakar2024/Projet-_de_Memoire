import gzip
import hashlib
import io
import json
import re

import polars as pl
import pytest

from ingestion.config import BRONZE, RAW
from ingestion.storage import (
    begin_partition,
    build_manifest,
    finalize_partition,
    get_bytes,
    partition_is_complete,
    partition_uri,
    put_bytes,
    read_manifest,
)
from transformations.raw_to_bronze import _normalize_column_name, _convert_flat_source, _convert_jsonl_source, raw_to_bronze


def test_normalize_column_name_lowercases_a_plain_word():
    assert _normalize_column_name("Assembly") == "assembly"


def test_normalize_column_name_has_no_word_boundary_without_a_separator():
    """Pas de coupure aux frontières minuscule->MAJUSCULE : aucun indice mécanique
    pour deviner où découper un nom sans séparateur d'origine."""
    assert _normalize_column_name("#AlleleID") == "alleleid"
    assert _normalize_column_name("GeneSymbol") == "genesymbol"


def test_normalize_column_name_collapses_separators_to_one_underscore():
    assert _normalize_column_name("RS# (dbSNP)") == "rs_dbsnp"
    assert _normalize_column_name("nsv/esv (dbVar)") == "nsv_esv_dbvar"


def test_normalize_column_name_keeps_an_existing_single_underscore():
    assert _normalize_column_name("HGVS_p") == "hgvs_p"


FLAT_TSV = (
    "#AlleleID\tGeneSymbol\tAssembly\n"
    "1\tBRCA1\tGRCh38\n"
    "\t\t\n"
    "2\tHBB\t\n"
)


FLAT_OBJECT = "variant_summary.txt.gz"


def _seed_flat_object(tmp_path, object_name=FLAT_OBJECT):
    import gzip

    partition = f"file://{tmp_path}/lake/raw/clinvar/dt=2026-09-01"
    put_bytes(f"{partition}/{object_name}", gzip.compress(FLAT_TSV.encode()))
    return partition


def test_convert_flat_source_normalizes_column_names_and_adds_technical_columns(tmp_path):
    partition = _seed_flat_object(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_flat_source(
        partition,
        FLAT_OBJECT,
        {"_source_version": "2026-09", "_logical_date": "2026-09-01", "_ingested_at": "2026-09-01T00:00:00+00:00"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df.columns == [
        "alleleid", "genesymbol", "assembly",
        "_source_version", "_logical_date", "_ingested_at",
    ]
    assert df.schema["alleleid"] == pl.Utf8


def test_convert_flat_source_drops_the_entirely_empty_row_keeps_the_incomplete_one(tmp_path):
    partition = _seed_flat_object(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_flat_source(
        partition, FLAT_OBJECT,
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df["alleleid"].to_list() == ["1", "2"]
    # ligne incomplète (Assembly vide pour HBB) conservée, pas de filtre par colonne
    assert df.filter(pl.col("genesymbol") == "HBB")["assembly"].to_list() == [None]


def test_convert_flat_source_streams_via_open_stream(tmp_path):
    """Garde de streaming : le fichier passe par open_stream (flux), jamais chargé
    d'un bloc. Un fixture de quelques lignes ne prouve pas la tenue mémoire sur les
    6M lignes réelles du bulk ClinVar — seule l'inspection du chemin de code
    l'atteste, comme pour ingest_medgen.py (test_ingest_medgen_streams_the_bulk)."""
    from unittest.mock import patch

    from ingestion.storage import open_stream

    partition = _seed_flat_object(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    with patch("transformations.raw_to_bronze.open_stream", wraps=open_stream) as espion:
        _convert_flat_source(
            partition, FLAT_OBJECT,
            {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
            work_dir,
        )

    assert espion.call_count == 1
    assert espion.call_args.args[0] == f"{partition}/{FLAT_OBJECT}"


JSONL_OBJECT = "gene_summaries.jsonl.gz"


def _seed_jsonl_object(tmp_path, records):
    partition = f"file://{tmp_path}/lake/raw/ncbi_gene/dt=2026-09-01/panel=brca"
    body = "".join(json.dumps(r) + "\n" for r in records)
    put_bytes(f"{partition}/{JSONL_OBJECT}", gzip.compress(body.encode()))
    return partition


def test_convert_jsonl_source_extracts_scalar_fields_as_columns(tmp_path):
    partition = _seed_jsonl_object(tmp_path, [
        {"gene_symbol": "BRCA1", "esummary": {"uid": "672", "name": "BRCA1"}},
        {"gene_symbol": "HBS1L", "esummary": {}},
    ])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df["gene_symbol"].to_list() == ["BRCA1", "HBS1L"]
    assert df.columns == ["gene_symbol", "esummary_json", "_source_version", "_logical_date", "_ingested_at"]


def test_convert_jsonl_source_serializes_the_nested_field_as_reparsable_json(tmp_path):
    partition = _seed_jsonl_object(tmp_path, [
        {"gene_symbol": "BRCA1", "esummary": {"uid": "672", "name": "BRCA1"}},
    ])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    parsed = json.loads(df["esummary_json"][0])
    assert parsed == {"uid": "672", "name": "BRCA1"}


def test_convert_jsonl_source_keeps_a_row_with_an_empty_nested_payload(tmp_path):
    """Un gène non résolu par NCBI Gene garde sa ligne, esummary vide — pas de ligne
    supprimée (cohérent avec un CUI MedGen non résolu, déjà légitime en raw)."""
    partition = _seed_jsonl_object(tmp_path, [
        {"gene_symbol": "HBS1L", "esummary": {}},
    ])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df["gene_symbol"].to_list() == ["HBS1L"]
    assert json.loads(df["esummary_json"][0]) == {}


def test_convert_jsonl_source_handles_multiple_scalar_and_nested_fields(tmp_path):
    """hpo_terms : trois champs scalaires, un champ imbriqué."""
    partition = f"file://{tmp_path}/lake/raw/hpo_terms/dt=2026-09-01/panel=sickle"
    records = [
        {"gene_symbol": "HBB", "hpo_id": "HP:0001903", "hpo_name": "Anemia",
         "details": {"definition": "A reduction in erythrocytes."}},
    ]
    body = "".join(json.dumps(r) + "\n" for r in records)
    put_bytes(f"{partition}/hpo_terms.jsonl.gz", gzip.compress(body.encode()))
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, "hpo_terms.jsonl.gz",
        ("gene_symbol", "hpo_id", "hpo_name"), ("details",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df.columns == [
        "gene_symbol", "hpo_id", "hpo_name", "details_json",
        "_source_version", "_logical_date", "_ingested_at",
    ]
    assert json.loads(df["details_json"][0])["definition"] == "A reduction in erythrocytes."


def test_convert_jsonl_source_produces_zero_rows_for_an_empty_source(tmp_path):
    """Une partition raw JSONL vide (zéro enregistrement) doit produire un Parquet à
    zéro ligne, pas une ligne fabriquée par la diffusion des colonnes techniques sur
    un DataFrame (0, 0) — cf. `pl.DataFrame(rows)` sans schéma explicite."""
    partition = _seed_jsonl_object(tmp_path, [])
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    output = _convert_jsonl_source(
        partition, JSONL_OBJECT, ("gene_symbol",), ("esummary",),
        {"_source_version": "v", "_logical_date": "d", "_ingested_at": "i"},
        work_dir,
    )

    df = pl.read_parquet(output)
    assert df.height == 0
    assert df.columns == ["gene_symbol", "esummary_json", "_source_version", "_logical_date", "_ingested_at"]
    assert df.schema["gene_symbol"] == pl.Utf8
    assert df.schema["esummary_json"] == pl.Utf8


def _seed_raw_flat(lake, source, logical_date, object_name, content: bytes, source_version, panel=None,
                   sha256=None):
    partition = partition_uri(RAW, source, logical_date, panel=panel, lake_uri=lake)
    begin_partition(partition)
    put_bytes(f"{partition}/{object_name}", content)
    finalize_partition(partition, build_manifest(
        source=source, logical_date=logical_date, source_url="https://example.org/src",
        source_version=source_version, files={object_name: len(content)}, record_count=2,
        panel=panel, sha256=sha256,
    ))
    return partition


def _seed_raw_jsonl(lake, source, logical_date, object_name, records, source_version, panel=None):
    body = gzip.compress("".join(json.dumps(r) + "\n" for r in records).encode())
    return _seed_raw_flat(lake, source, logical_date, object_name, body, source_version, panel=panel)


def _read_bronze_parquet(partition: str) -> pl.DataFrame:
    """Relit le Parquet écrit par raw_to_bronze via l'abstraction de stockage
    (get_bytes), comme le reste des tests du projet — jamais un chemin filesystem
    en dur, pour que ces tests restent valables si le lac passe un jour sur MinIO."""
    return pl.read_parquet(io.BytesIO(get_bytes(f"{partition}/data.parquet")))


def test_raw_to_bronze_converts_a_flat_shared_source(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_flat(
        lake, "hpo", "2026-09-01", "genes_to_phenotype.txt",
        b"ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n3043\tHBB\tHP:0001903\tAnemia\n",
        source_version="v2026.08.01",
    )

    partitions = raw_to_bronze("2026-09-01", ["hpo"], lake_uri=lake)

    assert partitions == [f"{lake}/bronze/hpo/dt=2026-09-01"]
    assert partition_is_complete(partitions[0])
    df = _read_bronze_parquet(partitions[0])
    assert df["gene_symbol"].to_list() == ["HBB"]


def test_raw_to_bronze_converts_a_jsonl_panel_source(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_jsonl(
        lake, "ncbi_gene", "2026-09-01", "gene_summaries.jsonl.gz",
        [{"gene_symbol": "BRCA1", "esummary": {"uid": "672"}}],
        source_version="2026-09-01", panel="brca",
    )

    partitions = raw_to_bronze("2026-09-01", ["ncbi_gene"], panel="brca", lake_uri=lake)

    assert partitions == [f"{lake}/bronze/ncbi_gene/dt=2026-09-01/panel=brca"]
    assert partition_is_complete(partitions[0])


def test_raw_to_bronze_manifest_traces_back_to_the_raw_partition(tmp_path):
    lake = f"file://{tmp_path}/lake"
    raw_partition = _seed_raw_jsonl(
        lake, "medgen", "2026-09-01", "concepts.jsonl.gz",
        [{"cui": "C0002895", "esummary": {"conceptmeta": "<OMIM/>"}}],
        source_version="2026-09-01", panel="sickle",
    )

    [bronze_partition] = raw_to_bronze("2026-09-01", ["medgen"], panel="sickle", lake_uri=lake)

    manifest = read_manifest(bronze_partition)
    assert manifest["source_url"] == raw_partition
    assert manifest["source_version"] == "2026-09-01"
    assert manifest["record_count"] == 1
    assert manifest["panel"] == "sickle"


def test_raw_to_bronze_propagates_technical_columns_from_the_raw_manifest(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_jsonl(
        lake, "refseq", "2026-09-01", "transcripts.jsonl.gz",
        [{"gene_symbol": "BRCA1", "transcripts": [{"accession": "NM_007294"}]}],
        source_version="2026-09-01", panel="brca",
    )

    [bronze_partition] = raw_to_bronze("2026-09-01", ["refseq"], panel="brca", lake_uri=lake)
    raw_manifest = read_manifest(partition_uri(RAW, "refseq", "2026-09-01", panel="brca", lake_uri=lake))

    df = _read_bronze_parquet(bronze_partition)
    assert df["_source_version"].to_list() == [raw_manifest["source_version"]]
    assert df["_logical_date"].to_list() == ["2026-09-01"]
    assert df["_ingested_at"].to_list() == [raw_manifest["written_at"]]


def test_raw_to_bronze_rejects_an_unknown_source(tmp_path):
    lake = f"file://{tmp_path}/lake"
    with pytest.raises(ValueError, match="source inconnue"):
        raw_to_bronze("2026-09-01", ["inconnue"], lake_uri=lake)


def test_raw_to_bronze_converts_every_source_it_is_given(tmp_path):
    """Boucle sur plusieurs sources partagées en un seul appel, comme le fait le DAG
    d'acquisition avec SHARED_SOURCES = ["clinvar", "hpo"]."""
    lake = f"file://{tmp_path}/lake"
    _seed_raw_flat(
        lake, "clinvar", "2026-09-01", "variant_summary.txt.gz",
        gzip.compress(b"#AlleleID\tGeneSymbol\n1\tBRCA1\n"), source_version="2026-09",
    )
    _seed_raw_flat(
        lake, "hpo", "2026-09-01", "genes_to_phenotype.txt",
        b"ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n3043\tHBB\tHP:0001903\tAnemia\n",
        source_version="v2026.08.01",
    )

    partitions = raw_to_bronze("2026-09-01", ["clinvar", "hpo"], lake_uri=lake)

    assert partitions == [
        f"{lake}/bronze/clinvar/dt=2026-09-01",
        f"{lake}/bronze/hpo/dt=2026-09-01",
    ]
    assert all(partition_is_complete(p) for p in partitions)


def test_raw_to_bronze_rejects_a_raw_partition_with_no_manifest(tmp_path):
    """Une partition raw jamais écrite (lac purgé, déclenchement manuel erroné) n'a
    pas de manifest : read_manifest renvoie None, qui doit lever un ValueError clair
    plutôt qu'un TypeError accidentel en indexant dedans."""
    lake = f"file://{tmp_path}/lake"
    raw_partition = partition_uri(RAW, "hpo", "2026-09-01", lake_uri=lake)

    with pytest.raises(ValueError, match=re.escape(raw_partition)):
        raw_to_bronze("2026-09-01", ["hpo"], lake_uri=lake)


def test_raw_to_bronze_finalizes_earlier_sources_when_a_later_one_fails(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_raw_flat(
        lake, "hpo", "2026-09-01", "genes_to_phenotype.txt",
        b"ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\n3043\tHBB\tHP:0001903\tAnemia\n",
        source_version="v2026.08.01",
    )
    # "inconnue" n'a pas de partition raw : sa conversion échoue avec ValueError,
    # après que "hpo" a déjà été converti et finalisé.

    with pytest.raises(ValueError, match="source inconnue"):
        raw_to_bronze("2026-09-01", ["hpo", "inconnue"], lake_uri=lake)

    hpo_bronze = partition_uri(BRONZE, "hpo", "2026-09-01", lake_uri=lake)
    assert partition_is_complete(hpo_bronze)
    inconnue_bronze = partition_uri(BRONZE, "inconnue", "2026-09-01", lake_uri=lake)
    assert not partition_is_complete(inconnue_bronze)


def test_raw_to_bronze_accepts_a_raw_object_matching_its_recorded_sha256(tmp_path):
    lake = f"file://{tmp_path}/lake"
    content = gzip.compress(FLAT_TSV.encode())
    _seed_raw_flat(lake, "clinvar", "2026-09-01", FLAT_OBJECT, content, "2026-09",
                   sha256={FLAT_OBJECT: hashlib.sha256(content).hexdigest()})

    [partition] = raw_to_bronze("2026-09-01", ["clinvar"], lake_uri=lake)

    assert partition_is_complete(partition)


def test_raw_to_bronze_refuses_a_raw_object_altered_since_its_deposit(tmp_path):
    """Un objet raw abîmé après le dépôt (C2) arrête la conversion au lieu de produire un bronze faux."""
    lake = f"file://{tmp_path}/lake"
    content = gzip.compress(FLAT_TSV.encode())
    _seed_raw_flat(lake, "clinvar", "2026-09-01", FLAT_OBJECT, content, "2026-09",
                   sha256={FLAT_OBJECT: hashlib.sha256(b"autre contenu").hexdigest()})

    with pytest.raises(ValueError, match="SHA-256"):
        raw_to_bronze("2026-09-01", ["clinvar"], lake_uri=lake)
    assert not partition_is_complete(partition_uri(BRONZE, "clinvar", "2026-09-01", lake_uri=lake))
