from ingestion.config import (
    ALL_GENES,
    BREAST_CANCER_GENES,
    SICKLE_CELL_GENES,
    EUTILS_BASE_URL,
)


def test_all_genes_combines_both_gene_lists():
    assert len(BREAST_CANCER_GENES) == 12
    assert len(SICKLE_CELL_GENES) == 6
    assert len(ALL_GENES) == 18
    assert set(ALL_GENES) == set(BREAST_CANCER_GENES) | set(SICKLE_CELL_GENES)


def test_sickle_cell_genes_uses_queryable_symbols_not_the_intergenic_locus():
    # "HBS1L-MYB" désigne la région intergénique modulatrice du taux d'HbF : ClinVar et
    # NCBI Gene ne la connaissent pas comme symbole (0 variant, esearch vide). Le locus est
    # couvert par ses deux gènes flanquants, qui sont eux interrogeables.
    assert "HBS1L-MYB" not in SICKLE_CELL_GENES
    assert {"HBS1L", "MYB"} <= set(SICKLE_CELL_GENES)


def test_all_genes_has_no_duplicates():
    assert len(ALL_GENES) == len(set(ALL_GENES))


def test_eutils_base_url_is_https():
    assert EUTILS_BASE_URL == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


from pathlib import Path

from ingestion.config import BRONZE, GOLD, RAW, SILVER, current_lake_uri


def test_current_lake_uri_defaults_to_local_data_lake(monkeypatch):
    monkeypatch.delenv("LAKE_URI", raising=False)
    uri = current_lake_uri()
    assert uri.startswith("file://")
    assert uri.endswith("/data/lake")
    assert Path(uri[len("file://"):]).is_absolute()


def test_current_lake_uri_reads_environment(monkeypatch):
    monkeypatch.setenv("LAKE_URI", "s3://")
    assert current_lake_uri() == "s3://"


def test_layer_names_are_the_four_medallion_buckets():
    assert (RAW, BRONZE, SILVER, GOLD) == ("raw", "bronze", "silver", "gold")
