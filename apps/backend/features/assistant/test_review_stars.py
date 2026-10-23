import ast
from pathlib import Path

import pytest

from features.assistant.review_stars import REVIEW_STATUS_STARS, stars_for

PIPELINE = Path(__file__).parents[4] / "src" / "transformations" / "silver_to_gold_analytique.py"


@pytest.mark.parametrize(
    ("status", "stars"),
    [
        ("practice guideline", 4),
        ("Reviewed by expert panel", 3),
        ("criteria provided, single submitter", 1),
        ("no assertion criteria provided", 0),
        ("something new from ClinVar", None),
        (None, None),
    ],
)
def test_stars(status, stars):
    assert stars_for(status) == stars


@pytest.mark.skipif(not PIPELINE.exists(), reason="pipeline absent")
def test_same_table_as_the_gold_layer():
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))
    (node,) = [
        n for n in tree.body
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "_REVIEW_STATUS_STARS" for t in n.targets)
    ]
    assert ast.literal_eval(node.value) == REVIEW_STATUS_STARS
