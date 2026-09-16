import polars as pl

from ingestion.storage import put_bytes
from transformations.raw_to_bronze import _normalize_column_name, _convert_flat_source


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
