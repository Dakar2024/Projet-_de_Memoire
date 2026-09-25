import polars as pl
import pytest

from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES
from transformations.bronze_to_silver import _write_clinvar_variant, _write_silver_snapshot
from transformations.quality_check_silver import SilverQualityError, quality_check_silver

ALL_TABLES = [
    "clinvar_variant", "clinvar_variant_gene", "clinvar_variant_disease", "ncbi_gene",
    "refseq_transcript", "medgen_concept", "medgen_mim", "medgen_inheritance",
    "hpo_gene_phenotype", "hpo_term",
]

_GENE_BY_PANEL = {"brca": BREAST_CANCER_GENES[0], "sickle": SICKLE_CELL_GENES[0]}


def _seed_complete_silver(lake, panel="brca", skip_table=None):
    uri = lambda table: f"{lake}/silver/{table}"
    gene = _GENE_BY_PANEL[panel]
    if skip_table != "clinvar_variant":
        _write_clinvar_variant(
            pl.DataFrame({
                "alleleid": ["1"], "panel": [panel], "clinicalsignificance": ["Benign"],
                "reviewstatus": ["criteria provided"], "lastevaluated": ["2026-08-01"],
            }),
            uri("clinvar_variant"), panel, "2026-08-01",
        )
    for table in ALL_TABLES:
        if table in (
            "clinvar_variant", "hpo_gene_phenotype", "clinvar_variant_gene",
            "clinvar_variant_disease",
        ):
            continue
        if table == skip_table:
            continue
        _write_silver_snapshot(
            pl.DataFrame({"panel": [panel], "gene_symbol": [gene]}), uri(table), panel
        )
    # hpo_gene_phenotype : vide légitime, mais présente (table créée).
    if skip_table != "hpo_gene_phenotype":
        _write_silver_snapshot(
            pl.DataFrame({"panel": [], "gene_symbol": []}, schema={"panel": pl.Utf8, "gene_symbol": pl.Utf8}),
            uri("hpo_gene_phenotype"), panel,
        )
    if skip_table != "clinvar_variant_gene":
        _write_silver_snapshot(
            pl.DataFrame({"panel": [panel], "alleleid": ["1"], "gene_symbol": [gene]}),
            uri("clinvar_variant_gene"), panel,
        )
    if skip_table != "clinvar_variant_disease":
        _write_silver_snapshot(
            pl.DataFrame({"panel": [panel], "alleleid": ["1"], "disease_name": ["Some disease"]}),
            uri("clinvar_variant_disease"), panel,
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


def test_quality_check_silver_reports_a_missing_table_as_a_silver_quality_error(tmp_path):
    """Une table Silver absente (ex. run bronze_to_silver interrompu) doit lever
    SilverQualityError, avec le nom de la table et « absente » dans le message —
    pas la TableNotFoundError opaque de delta-rs, et sans abandonner les contrôles
    suivants."""
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake, skip_table="medgen_mim")

    with pytest.raises(SilverQualityError, match="medgen_mim.*absente"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_silver_rejects_a_dangling_alleleid_in_clinvar_variant_gene(tmp_path):
    """Un alleleid présent dans clinvar_variant_gene sans ligne correspondante dans
    clinvar_variant est une référence pendante (régression C4) : elle doit être
    signalée, pas laissée passer silencieusement."""
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)
    _write_silver_snapshot(
        pl.DataFrame({"panel": ["brca"], "alleleid": ["999"], "gene_symbol": [_GENE_BY_PANEL["brca"]]}),
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


def test_quality_check_silver_rejects_a_dangling_variant_disease(tmp_path):
    """Un alleleid de clinvar_variant_disease sans ligne dans clinvar_variant
    produirait une maladie rattachée à un variant inexistant dans le Gold."""
    lake = f"file://{tmp_path}/lake"
    _seed_complete_silver(lake)
    _write_silver_snapshot(
        pl.DataFrame({"panel": ["brca"], "alleleid": ["999"], "disease_name": ["X"]}),
        f"{lake}/silver/clinvar_variant_disease", "brca",
    )

    with pytest.raises(SilverQualityError, match="clinvar_variant_disease"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)


def _seed_variants_and_snapshot(lake, courants, dans_instantane, panel="brca"):
    """Sème `courants` variants encore is_current et un instantané du mois n'en
    couvrant que `dans_instantane` : l'écart est exactement la population que le
    contrôle de plausibilité surveille."""
    gene = _GENE_BY_PANEL[panel]
    _seed_complete_silver(lake, panel=panel)
    _write_clinvar_variant(
        pl.DataFrame({
            "alleleid": [str(i) for i in range(courants)],
            "panel": [panel] * courants,
            "clinicalsignificance": ["Benign"] * courants,
            "reviewstatus": ["criteria provided"] * courants,
            "lastevaluated": ["2026-08-01"] * courants,
        }),
        f"{lake}/silver/clinvar_variant", panel, "2026-09-01",
    )
    _write_silver_snapshot(
        pl.DataFrame({
            "panel": [panel] * dans_instantane,
            "alleleid": [str(i) for i in range(dans_instantane)],
            "gene_symbol": [gene] * dans_instantane,
        }),
        f"{lake}/silver/clinvar_variant_gene", panel,
    )
    _write_silver_snapshot(
        pl.DataFrame({
            "panel": [panel] * dans_instantane,
            "alleleid": [str(i) for i in range(dans_instantane)],
            "disease_name": ["X"] * dans_instantane,
        }),
        f"{lake}/silver/clinvar_variant_disease", panel,
    )


def test_quality_check_silver_accepts_a_handful_of_retired_variants(tmp_path):
    """Quelques variants retirés par ClinVar d'un mois sur l'autre sont normaux :
    le contrôle ne doit pas bloquer un run légitime."""
    lake = f"file://{tmp_path}/lake"
    _seed_variants_and_snapshot(lake, courants=100, dans_instantane=98)

    quality_check_silver("2026-09-01", "brca", lake_uri=lake)  # ne lève pas


def test_quality_check_silver_rejects_a_truncated_clinvar_archive(tmp_path):
    """Angle mort documenté : le MERGE SCD2 ne clôture jamais un variant absent du
    nouveau lot, donc `clinvar_variant` ne rétrécit pas tandis que les instantanés
    rétrécissent. Sans ce contrôle, une archive tronquée laisserait tous les autres
    contrôles verts pendant que le Silver diverge de sa source."""
    lake = f"file://{tmp_path}/lake"
    _seed_variants_and_snapshot(lake, courants=100, dans_instantane=40)

    with pytest.raises(SilverQualityError, match="clinvar_variant"):
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_silver_names_the_proportion_of_retired_variants(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed_variants_and_snapshot(lake, courants=100, dans_instantane=40)

    with pytest.raises(SilverQualityError) as raised:
        quality_check_silver("2026-09-01", "brca", lake_uri=lake)

    message = str(raised.value)
    assert "60" in message and "%" in message
