from dags.common.panels import PANEL_SOURCES, PANELS, SHARED_SOURCES
from ingestion.config import BREAST_CANCER_GENES, SICKLE_CELL_GENES


def test_panels_reuse_the_tested_gene_lists_without_duplicating_them():
    """La liste de gènes a une seule source de vérité, déjà couverte par test_config.py."""
    assert PANELS["brca"] == BREAST_CANCER_GENES
    assert PANELS["sickle"] == SICKLE_CELL_GENES


def test_panels_cover_every_gene_of_the_project():
    covered = {gene for genes in PANELS.values() for gene in genes}
    assert len(covered) == 18


def test_sources_are_split_between_shared_and_panel_without_overlap():
    """Une source partagée convertie aussi par panel serait traitée deux fois ;
    une source oubliée ne serait jamais convertie."""
    assert set(SHARED_SOURCES) == {"clinvar", "hpo"}
    assert set(PANEL_SOURCES) == {"ncbi_gene", "refseq", "medgen", "hpo_terms"}
    assert not set(SHARED_SOURCES) & set(PANEL_SOURCES)
