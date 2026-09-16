import polars as pl
import pytest

from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES
from transformations.bronze_to_silver import _write_clinvar_variant, _write_silver_snapshot
from transformations.quality_check_silver import SilverQualityError, quality_check_silver

ALL_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "ncbi_gene", "refseq_transcript",
    "medgen_concept", "medgen_mim", "medgen_inheritance", "hpo_gene_phenotype", "hpo_term",
]

_GENE_BY_PANEL = {"brca": BREAST_CANCER_GENES[0], "sickle": SICKLE_CELL_GENES[0]}


def _seed_complete_silver(lake, panel="brca"):
    uri = lambda table: f"{lake}/silver/{table}"
    gene = _GENE_BY_PANEL[panel]
    _write_clinvar_variant(
        pl.DataFrame({
            "alleleid": ["1"], "panel": [panel], "clinicalsignificance": ["Benign"],
            "reviewstatus": ["criteria provided"], "lastevaluated": ["2026-08-01"],
        }),
        uri("clinvar_variant"), panel, "2026-08-01",
    )
    for table in ALL_TABLES:
        if table in ("clinvar_variant", "hpo_gene_phenotype", "clinvar_variant_gene"):
            continue
        _write_silver_snapshot(
            pl.DataFrame({"panel": [panel], "gene_symbol": [gene]}), uri(table), panel
        )
    # hpo_gene_phenotype : vide légitime, mais présente (table créée).
    _write_silver_snapshot(
        pl.DataFrame({"panel": [], "gene_symbol": []}, schema={"panel": pl.Utf8, "gene_symbol": pl.Utf8}),
        uri("hpo_gene_phenotype"), panel,
    )
    _write_silver_snapshot(
        pl.DataFrame({"panel": [panel], "alleleid": ["1"], "gene_symbol": [gene]}),
        uri("clinvar_variant_gene"), panel,
    )


def test_quality_check_silver_passes_on_a_complete_run(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)

    quality_check_silver("2026-09-01", "brca", lake_uri=lake)  # ne lève pas


def test_quality_check_silver_allows_an_empty_hpo_gene_phenotype(tmp_path):
    """HBS1L/MYB (sickle) n'ont légitimement aucune ligne dans hpo_gene_phenotype."""
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake, panel="sickle")

    quality_check_silver("2026-09-01", "sickle", lake_uri=lake)  # ne lève pas


def test_quality_check_silver_rejects_a_gene_outside_the_panel(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)
    # HBB est dans le panel sickle, pas brca
    _write_silver_snapshot(
        pl.DataFrame({"panel": ["brca"], "alleleid": ["2"], "gene_symbol": ["HBB"]}),
        f"{lake}/silver/clinvar_variant_gene", "brca",
    )

    with pytest.raises(SilverQualityError, match="clinvar_variant_gene"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_silver_rejects_two_current_rows_for_the_same_variant(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)
    import polars as pl
    pl.DataFrame({
        "alleleid": ["1"], "panel": ["brca"], "clinicalsignificance": ["Pathogenic"],
        "reviewstatus": ["criteria provided"], "lastevaluated": ["2026-09-01"],
        "valid_from": ["2026-09-01"], "valid_to": [None], "is_current": [True],
    }, schema={
        "alleleid": pl.Utf8, "panel": pl.Utf8, "clinicalsignificance": pl.Utf8,
        "reviewstatus": pl.Utf8, "lastevaluated": pl.Utf8,
        "valid_from": pl.Utf8, "valid_to": pl.Utf8, "is_current": pl.Boolean,
    }).write_delta(f"{lake}/silver/clinvar_variant", mode="append")

    with pytest.raises(SilverQualityError, match="clinvar_variant"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)
