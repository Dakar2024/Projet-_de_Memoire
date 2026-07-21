from ingestion.config import (
    ALL_GENES,
    BREAST_CANCER_GENES,
    SICKLE_CELL_GENES,
    EUTILS_BASE_URL,
)


def test_all_genes_combines_both_gene_lists():
    assert len(BREAST_CANCER_GENES) == 12
    assert len(SICKLE_CELL_GENES) == 5
    assert len(ALL_GENES) == 17
    assert set(ALL_GENES) == set(BREAST_CANCER_GENES) | set(SICKLE_CELL_GENES)


def test_all_genes_has_no_duplicates():
    assert len(ALL_GENES) == len(set(ALL_GENES))


def test_eutils_base_url_is_https():
    assert EUTILS_BASE_URL == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
