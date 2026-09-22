import pytest

from transformations.silver_to_gold_analytique import silver_to_gold_analytique


def test_silver_to_gold_analytique_names_sub_project_d():
    with pytest.raises(NotImplementedError, match="sous-projet D"):
        silver_to_gold_analytique("2026-09-01", "brca")
