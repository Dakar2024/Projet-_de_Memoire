import pytest

from transformations.raw_to_bronze import raw_to_bronze
from transformations.silver_to_gold_analytique import silver_to_gold_analytique
from transformations.silver_to_gold_rag import silver_to_gold_rag


def test_raw_to_bronze_names_sub_project_b():
    """Le message doit dire qui reprendra la tâche : un échec muet ou générique
    dans Airflow ne dirait pas où le pipeline s'arrête volontairement."""
    with pytest.raises(NotImplementedError, match="sous-projet B"):
        raw_to_bronze("2026-09-01", ["clinvar", "hpo"])


def test_silver_to_gold_rag_names_sub_project_d():
    with pytest.raises(NotImplementedError, match="sous-projet D"):
        silver_to_gold_rag("2026-09-01", "brca")


def test_silver_to_gold_analytique_names_sub_project_d():
    with pytest.raises(NotImplementedError, match="sous-projet D"):
        silver_to_gold_analytique("2026-09-01", "brca")
