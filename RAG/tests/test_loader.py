import polars as pl
import pytest

from RAG.src.ingestion.loader import DOCUMENT_COLUMNS, load_gold_documents
from RAG.src.utils.errors import RagPermanentError
from transformations.silver_to_gold_rag import documents_uri


def _doc(doc_id: str, panel: str) -> dict:
    return {
        "doc_id": doc_id, "chunk_id": f"h-{doc_id}", "doc_type": "variant", "text": f"texte {doc_id}",
        "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic", "review_status": "reviewed",
        "rs_dbsnp": 80357498, "hgvs_c": "c.116G>A", "hgvs_p": "p.Cys39Tyr",
        "clinvar_variation_id": "37392", "clinvar_url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/37392/",
        "source_version": "2026-09", "collected_at": "2026-09-01", "panel": panel,
    }


def _seed(lake: str, rows: list[dict]) -> None:
    pl.DataFrame(rows).write_delta(
        documents_uri(lake), mode="overwrite", delta_write_options={"partition_by": ["panel"]}
    )


def test_reads_only_the_requested_panel_sorted_by_doc_id(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed(lake, [_doc("clinvar:2", "brca"), _doc("clinvar:1", "brca"), _doc("clinvar:9", "sickle")])

    documents = load_gold_documents("brca", lake_uri=lake)

    assert documents.columns == DOCUMENT_COLUMNS
    assert documents["doc_id"].to_list() == ["clinvar:1", "clinvar:2"]


def test_a_missing_table_reads_as_empty(tmp_path):
    """Le garde-fou de l'indexation refuse ensuite un Gold vide : la lecture ne doit
    pas lever une erreur de bas niveau qui masquerait ce refus explicite."""
    documents = load_gold_documents("brca", lake_uri=f"file://{tmp_path}/lake")

    assert documents.is_empty()
    assert documents.columns == DOCUMENT_COLUMNS


def test_duplicate_doc_ids_are_refused(tmp_path):
    lake = f"file://{tmp_path}/lake"
    _seed(lake, [_doc("clinvar:1", "brca"), _doc("clinvar:1", "brca")])

    with pytest.raises(RagPermanentError, match="clinvar:1"):
        load_gold_documents("brca", lake_uri=lake)
