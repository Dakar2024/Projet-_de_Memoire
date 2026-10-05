import pytest

from RAG.experiments.mesure_recherche import choose_model, score_question, significance_accuracy

K = 10


def test_part1_family_a_scores_the_reciprocal_rank_within_k():
    q = {"part": 1, "family": "A"}

    assert score_question(q, ["x", "gene:BRCA1"], [], {}, {"gene:BRCA1"}, K) == pytest.approx(0.5)
    assert score_question(q, ["x", "y"], [], {}, {"gene:BRCA1"}, K) == 0.0


def test_part1_families_b_c_score_precision_at_k():
    q = {"part": 1, "family": "C"}

    assert score_question(q, ["a", "b", "c"], [], {}, {"a", "c"}, K) == pytest.approx(0.2)


def test_part2_requires_an_exact_document_first():
    q = {"part": 2}

    assert score_question(q, ["clinvar:1", "x"], [], {}, {"clinvar:1"}, K) == 1.0
    assert score_question(q, ["x", "clinvar:1"], [], {}, {"clinvar:1"}, K) == 0.0
    assert score_question(q, [], [], {}, {"clinvar:1"}, K) == 0.0


def test_part3_requires_expected_flags_and_no_invented_identifier():
    q = {"part": 3, "expected_flags": ["identifier_not_found"],
         "expected_identifiers": {"rs": [9999999999], "hgvs_c": [], "hgvs_p": [], "genes": []}}
    ids = {"rs": [9999999999], "hgvs_c": [], "hgvs_p": [], "genes": [], "out_of_panel": []}

    assert score_question(q, [], ["identifier_not_found"], ids, set(), K) == 1.0
    assert score_question(q, [], [], ids, set(), K) == 0.0
    assert score_question(q, [], ["identifier_not_found"], {**ids, "rs": [1]}, set(), K) == 0.0


def test_choose_model_takes_the_best_when_others_are_clearly_worse():
    scores = {"cher": [1.0] * 30, "moyen": [0.2] * 30, "bon_marche": [0.1] * 30}
    costs = {"cher": 1.0, "moyen": 0.4, "bon_marche": 0.01}

    choice, details = choose_model(scores, costs)

    assert choice == "cher" and details["best"] == "cher"


def test_choose_model_takes_the_cheapest_indistinguishable_model():
    scores = {"cher": [1.0, 0.0] * 15, "bon_marche": [0.0, 1.0] * 15}
    costs = {"cher": 1.0, "bon_marche": 0.01}

    choice, details = choose_model(scores, costs)

    assert choice == "bon_marche"
    assert details["indistinguishable"] == ["bon_marche", "cher"]


def test_choose_model_is_reproducible():
    scores = {"a": [0.5, 0.7, 0.9] * 10, "b": [0.4, 0.8, 0.85] * 10}
    costs = {"a": 1.0, "b": 0.5}

    assert choose_model(scores, costs) == choose_model(scores, costs)


def test_significance_accuracy():
    questions = [{"id": "q1", "expected_significance": "pathogenic"},
                 {"id": "q2", "expected_significance": "none"}]
    analyses = {"q1": {"significance": "pathogenic"}, "q2": {"significance": "benign"}}

    assert significance_accuracy(questions, analyses) == 0.5
