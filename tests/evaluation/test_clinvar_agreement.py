import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest

from evaluation.clinvar_agreement import (
    ClinvarSummary,
    SilverVariant,
    Verdict,
    compare,
    parse_date,
    parse_rcv_conditions,
    wilson_interval,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "clinvar_esummary"


# Extrait réel du XML VCV (`efetch`, `rettype=vcv`) : les conditions des RCV de chaque variation.
RCV_CONDITIONS = parse_rcv_conditions((FIXTURES / "vcv_rcv.xml").read_text("utf-8"))


def _summary(uid: str) -> ClinvarSummary | None:
    record = json.loads((FIXTURES / f"{uid}.json").read_text("utf-8"))
    return ClinvarSummary.from_esummary(record, RCV_CONDITIONS.get(uid, frozenset()))


# Valeurs du Silver d'octobre 2026 pour la variation 37392 (BRCA1 c.116G>A).
OURS_37392 = SilverVariant(
    variation_id="37392",
    name="NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr)",
    significance="Pathogenic/Likely pathogenic",
    review_status="criteria provided, multiple submitters, no conflicts",
    last_evaluated="Jul 14, 2026",
    rs_dbsnp=80357498,
    diseases=frozenset({
        "Breast-ovarian cancer, familial, susceptibility to, 1",
        "Hereditary cancer-predisposing syndrome",
        "Hereditary breast ovarian cancer syndrome",
        "Breast neoplasm",
    }),
)


def _failed(comparison) -> set[str]:
    return {check.field for check in comparison.checks if not check.ok}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Jul 14, 2026", dt.date(2026, 7, 14)),
        ("2026/07/14 00:00", dt.date(2026, 7, 14)),
        ("-", None),
        ("", None),
        (None, None),
        # Sentinelle de l'API pour une variation jamais évaluée.
        ("1/01/01 00:00", None),
    ],
)
def test_parse_date_reads_silver_and_api_formats(text, expected):
    assert parse_date(text) == expected


def test_parse_date_rejects_an_unknown_format():
    with pytest.raises(ValueError):
        parse_date("14/07/2026")


def test_summary_reads_the_fields_of_a_real_record():
    summary = _summary("37392")
    assert summary.title == "NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr)"
    assert summary.significance == "Pathogenic/Likely pathogenic"
    assert summary.last_evaluated == dt.date(2026, 7, 14)
    assert summary.rs_dbsnp == frozenset({80357498})
    assert summary.diseases == RCV_CONDITIONS["37392"]


def test_rcv_conditions_drop_placeholder_labels():
    assert "Malignant tumor of urinary bladder" in RCV_CONDITIONS["37392"]
    assert "not provided" not in RCV_CONDITIONS["37392"]
    assert RCV_CONDITIONS["1336926"] == frozenset()
    assert set(RCV_CONDITIONS) == {"37392", "1048666", "1336926", "242797", "125855"}


def test_diseases_are_compared_with_the_rcv_conditions_not_the_germline_traits():
    # 125855 : « susceptibility to, 1 » est la maladie d'un RCV, absente du trait_set germinal
    # de l'esummary ; notre `PhenotypeList` liste les maladies par RCV (README de ClinVar).
    record = json.loads((FIXTURES / "125855.json").read_text("utf-8"))
    germline = {trait["trait_name"] for trait in record["germline_classification"]["trait_set"]}
    disease = "Breast-ovarian cancer, familial, susceptibility to, 1"
    assert disease not in germline
    ours = SilverVariant(
        variation_id="125855",
        name="NM_007294.4(BRCA1):c.5468-18T>A",
        significance="Conflicting classifications of pathogenicity",
        review_status="criteria provided, conflicting classifications",
        last_evaluated="Oct 26, 2023",
        rs_dbsnp=80358157,
        diseases=frozenset({
            disease, "Hereditary breast ovarian cancer syndrome", "Hereditary cancer-predisposing syndrome",
        }),
    )
    assert compare(ours, _summary("125855")).verdict is Verdict.AGREES


def test_summary_of_a_missing_record_is_none():
    assert _summary("999999999") is None


def test_identical_values_agree():
    comparison = compare(OURS_37392, _summary("37392"))
    assert comparison.verdict is Verdict.AGREES
    assert _failed(comparison) == set()


def test_changed_significance_with_a_later_api_date_is_a_later_update():
    ours = dataclasses.replace(
        OURS_37392, significance="Likely pathogenic", last_evaluated="Jan 10, 2026"
    )
    comparison = compare(ours, _summary("37392"))
    assert comparison.verdict is Verdict.LATER_UPDATE
    assert _failed(comparison) == {"significance"}


def test_changed_review_status_with_a_later_api_date_is_a_later_update():
    ours = dataclasses.replace(
        OURS_37392, review_status="criteria provided, single submitter", last_evaluated="Jan 10, 2026"
    )
    assert compare(ours, _summary("37392")).verdict is Verdict.LATER_UPDATE


def test_changed_significance_with_the_same_date_is_a_mismatch():
    ours = dataclasses.replace(OURS_37392, significance="Likely pathogenic")
    assert compare(ours, _summary("37392")).verdict is Verdict.MISMATCH


def test_an_api_date_earlier_than_ours_is_a_mismatch_in_itself():
    ours = dataclasses.replace(OURS_37392, last_evaluated="Aug 01, 2026")
    comparison = compare(ours, _summary("37392"))
    assert comparison.verdict is Verdict.MISMATCH
    assert _failed(comparison) == {"last_evaluated"}


def test_a_later_api_date_never_excuses_a_different_hgvs_name():
    ours = dataclasses.replace(
        OURS_37392, name="NM_007294.3(BRCA1):c.116G>A (p.Cys39Tyr)", last_evaluated="Jan 10, 2026"
    )
    comparison = compare(ours, _summary("37392"))
    assert comparison.verdict is Verdict.MISMATCH
    assert _failed(comparison) == {"name"}


def test_a_later_api_date_never_excuses_a_different_dbsnp():
    ours = dataclasses.replace(OURS_37392, rs_dbsnp=1, last_evaluated="Jan 10, 2026")
    assert compare(ours, _summary("37392")).verdict is Verdict.MISMATCH


def test_dbsnp_absent_on_both_sides_agrees():
    ours = SilverVariant(
        variation_id="1048666",
        name="NC_000011.10:g.5224303_5227790del",
        significance="Pathogenic",
        review_status="no assertion criteria provided",
        last_evaluated="Mar 01, 2021",
        rs_dbsnp=-1,
        diseases=frozenset({"beta Thalassemia"}),
    )
    assert compare(ours, _summary("1048666")).verdict is Verdict.AGREES


def test_dbsnp_absent_only_on_our_side_is_a_mismatch():
    ours = dataclasses.replace(OURS_37392, rs_dbsnp=-1)
    assert _failed(compare(ours, _summary("37392"))) == {"rs_dbsnp"}


def test_our_diseases_may_be_a_subset_of_the_api_ones():
    ours = dataclasses.replace(OURS_37392, diseases=frozenset({"Breast neoplasm"}))
    assert compare(ours, _summary("37392")).verdict is Verdict.AGREES


def test_a_disease_absent_from_the_api_is_a_mismatch():
    ours = dataclasses.replace(OURS_37392, diseases=OURS_37392.diseases | {"Fanconi anemia"})
    assert _failed(compare(ours, _summary("37392"))) == {"diseases"}


def test_placeholder_api_labels_are_ignored():
    # Multi-gènes (TP53;WRAP53) dont les deux seules maladies sont des libellés vides.
    ours = SilverVariant(
        variation_id="1336926",
        name="NM_001143992.2(WRAP53):c.1A>G (p.Met1Val)",
        significance="Uncertain significance",
        review_status="criteria provided, multiple submitters, no conflicts",
        last_evaluated="Sep 01, 2022",
        rs_dbsnp=867179605,
        diseases=frozenset(),
    )
    summary = _summary("1336926")
    assert compare(ours, summary).verdict is Verdict.AGREES


def test_a_date_missing_on_both_sides_agrees():
    ours = SilverVariant(
        variation_id="242797",
        name="NM_001360016.2(G6PD):c.317C>G (p.Ser106Cys)",
        significance="no classification for the single variant",
        review_status="no classification for the single variant",
        last_evaluated="-",
        rs_dbsnp=267606835,
        diseases=frozenset(),
    )
    assert compare(ours, _summary("242797")).verdict is Verdict.AGREES


def test_an_api_date_where_we_had_none_counts_as_later():
    ours = dataclasses.replace(OURS_37392, significance="Uncertain significance", last_evaluated="-")
    assert compare(ours, _summary("37392")).verdict is Verdict.LATER_UPDATE


def test_a_missing_record_is_classed_apart():
    comparison = compare(OURS_37392, None)
    assert comparison.verdict is Verdict.MISSING
    assert comparison.checks == ()


def test_wilson_interval_matches_the_hand_computed_value():
    # p = 0,95 ; z² / n = 0,009604 → centre 0,945720, demi-largeur 0,021683.
    low, high = wilson_interval(380, 400)
    assert low == pytest.approx(0.92404, abs=1e-5)
    assert high == pytest.approx(0.96740, abs=1e-5)


def test_wilson_interval_of_a_perfect_score_stays_below_one():
    low, high = wilson_interval(400, 400)
    assert high == pytest.approx(1.0)
    assert low == pytest.approx(0.99049, abs=1e-5)


def test_wilson_interval_refuses_an_empty_sample():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_our_dash_sentinel_equals_an_empty_api_value():
    # Variant sans classification germinale : `-` dans le fichier, chaîne vide dans l'API (piège 3).
    ours = dataclasses.replace(
        OURS_37392, significance="-", review_status="-", last_evaluated="-", diseases=frozenset()
    )
    summary = dataclasses.replace(
        _summary("37392"), significance="", review_status="", last_evaluated=None
    )
    assert compare(ours, summary).verdict is Verdict.AGREES
