import polars as pl
import pytest

from evaluation.clinvar_agreement import Comparison, FieldCheck, Verdict
from scripts.verifier_justesse import allocate, draw_sample, summarize


def _current(brca: int, sickle: int) -> pl.DataFrame:
    return pl.DataFrame({
        "variationid": [str(i) for i in range(brca + sickle)],
        "panel": ["brca"] * brca + ["sickle"] * sickle,
    })


def test_allocate_is_proportional_and_sums_to_the_size():
    # Silver d'octobre 2026 : 93 615 brca, 3 577 sickle → 385,28 et 14,72.
    assert allocate({"brca": 93615, "sickle": 3577}, 400) == {"brca": 385, "sickle": 15}


def test_allocate_gives_the_remainder_to_the_largest_fractions():
    assert allocate({"a": 1, "b": 1, "c": 1}, 2) == {"a": 1, "b": 1, "c": 0}
    assert sum(allocate({"a": 5, "b": 3, "c": 2}, 7).values()) == 7


def test_allocate_refuses_a_sample_larger_than_the_population():
    with pytest.raises(ValueError):
        allocate({"brca": 3}, 4)


def test_draw_sample_is_reproducible_whatever_the_row_order():
    current = _current(900, 100)
    first = draw_sample(current, 40, seed=20261023)
    second = draw_sample(current.reverse(), 40, seed=20261023)
    assert first == second
    assert len(first) == 40
    assert sum(1 for row in first if row["panel"] == "sickle") == 4


def test_draw_sample_has_no_duplicates():
    sample = draw_sample(_current(300, 30), 100, seed=1)
    assert len({row["variation_id"] for row in sample}) == 100


def _comparison(variation_id: str, verdict: Verdict, failed: str | None = None) -> Comparison:
    checks = tuple(
        FieldCheck(field, "a", "b" if field == failed else "a", field != failed)
        for field in ("name", "significance")
    )
    return Comparison(variation_id, verdict, () if verdict is Verdict.MISSING else checks)


def test_summarize_excludes_missing_records_from_the_denominator():
    comparisons = [
        _comparison("1", Verdict.AGREES),
        _comparison("2", Verdict.LATER_UPDATE, "significance"),
        _comparison("3", Verdict.MISMATCH, "name"),
        _comparison("4", Verdict.MISSING),
    ]
    summary = summarize(comparisons)
    assert summary["verdicts"] == {"conforme": 1, "mise_a_jour": 1, "ecart": 1, "absente": 1}
    assert summary["compared"] == 3
    assert summary["agreement_rate"] == pytest.approx(2 / 3)
    assert summary["failed_by_field"] == {"name": 1, "significance": 1}
    assert 0 < summary["wilson_95"][0] < 2 / 3 < summary["wilson_95"][1] < 1
