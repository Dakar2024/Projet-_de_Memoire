import polars as pl
import pytest

from evaluation.clinvar_agreement import Comparison, FieldCheck, SilverVariant, Verdict
from scripts.verifier_justesse import (
    GridEntry,
    ProtocolCase,
    allocate,
    draw_sample,
    render_grid,
    resolve_sample,
    summarize,
)


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


def _candidates() -> pl.DataFrame:
    return pl.DataFrame({
        "variationid": ["10", "11", "12", "20"],
        "panel": ["brca"] * 3 + ["sickle"],
        "genesymbol": ["BRCA2", "BRCA2", "BRCA2", "HBB"],
        "clinicalsignificance": ["Benign", "Benign", "Pathogenic", "Pathogenic"],
        "reviewstatus": ["reviewed by expert panel"] * 3 + ["no assertion criteria provided"],
        "rs_dbsnp": [1, 2, 3, -1],
    })


_BENIGN = ProtocolCase(4, "96762", "BRCA2 bénin, panel d'experts", {
    "genesymbol": "BRCA2", "clinicalsignificance": "Benign", "reviewstatus": "reviewed by expert panel",
})


def test_resolve_sample_keeps_a_variant_still_in_the_gold():
    case = ProtocolCase(4, "11", "BRCA2 bénin", _BENIGN.criteria)
    assert resolve_sample([case], _candidates(), seed=1) == [(case, "11", None)]


def test_resolve_sample_replaces_a_vanished_variant_by_one_of_the_same_case():
    [(_case, chosen, replaced)] = resolve_sample([_BENIGN], _candidates(), seed=1)
    assert chosen in {"10", "11"}
    assert replaced == "96762"
    # Rejouable : même graine, même remplaçant, quel que soit l'ordre des lignes.
    assert resolve_sample([_BENIGN], _candidates().reverse(), seed=1)[0][1] == chosen


def test_resolve_sample_never_picks_the_same_replacement_twice():
    other = ProtocolCase(5, "1", "autre bénin", _BENIGN.criteria)
    chosen = [variant for _, variant, _ in resolve_sample([_BENIGN, other], _candidates(), seed=1)]
    assert sorted(chosen) == ["10", "11"]


def test_resolve_sample_matches_a_missing_dbsnp():
    case = ProtocolCase(11, "1048666", "HBB sans dbSNP", {"genesymbol": "HBB", "rs_dbsnp": -1})
    assert resolve_sample([case], _candidates(), seed=1)[0][1] == "20"


def test_resolve_sample_fails_when_a_case_has_no_candidate_left():
    case = ProtocolCase(1, "1", "introuvable", {"genesymbol": "ATM"})
    with pytest.raises(ValueError, match="introuvable"):
        resolve_sample([case], _candidates(), seed=1)


def _entry(**overrides) -> GridEntry:
    values = {
        "case": ProtocolCase(8, "1018969", "PTEN pathogène sans dbSNP", {}),
        "replaced_from": None,
        "variant": SilverVariant(
            variation_id="1018969", name="NM_000314.8(PTEN):c.141_142inv",
            significance="Pathogenic", review_status="criteria provided, single submitter",
            last_evaluated="Jul 22, 2024", rs_dbsnp=-1, diseases=frozenset({"PTEN hamartoma tumor syndrome"}),
        ),
        "genesymbol": "PTEN",
        "clinvar_url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/1018969/",
        "document": "Variant NM_000314.8(PTEN):c.141_142inv, gene PTEN.",
    }
    return GridEntry(**(values | overrides))


def _grid(entries: list[GridEntry]) -> str:
    return render_grid(entries, sentinels={"rs-1": 0, "None": 0}, annex=[], month="2026-10")


def test_render_grid_prefills_our_values_and_the_link():
    grid = _grid([_entry()])
    assert "https://www.ncbi.nlm.nih.gov/clinvar/variation/1018969/" in grid
    assert "NM_000314.8(PTEN):c.141_142inv" in grid
    assert "Jul 22, 2024" in grid
    assert "PTEN hamartoma tumor syndrome" in grid
    assert "Variant NM_000314.8(PTEN):c.141_142inv, gene PTEN." in grid


def test_render_grid_spells_out_a_missing_dbsnp():
    grid = _grid([_entry()])
    assert "aucun (`-1`)" in grid
    assert "rs-1 |" not in grid


def test_render_grid_traces_a_replacement():
    grid = _grid([_entry(replaced_from="999")])
    assert "remplace 999" in grid


def test_render_grid_has_one_summary_row_per_variant():
    grid = _grid([_entry(), _entry(case=ProtocolCase(9, "1336926", "multi-gènes", {}))])
    summary = grid.split("## Grille", 1)[1]
    assert summary.count("☐ conforme ☐ mise à jour postérieure ☐ **écart**") == 2
