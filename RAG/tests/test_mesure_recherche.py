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


# --- Garde-fous de la mesure -------------------------------------------------------------

import polars as pl

from RAG.experiments.mesure_recherche import (
    check_complete_field, check_run_manifest, check_runs_consistency, exact_doc_ids, v0_scores,
)
from RAG.src.retrieval.identifiers import Identifiers


def test_choose_model_refuses_an_empty_field():
    with pytest.raises(ValueError):
        choose_model({}, {})


def test_v0_scores_groups_e1_scores_by_family():
    qs = [{"id": "P1-A01", "part": 1, "family": "A"}, {"id": "P1-B01", "part": 1, "family": "B"},
          {"id": "P2-01", "part": 2}]

    assert v0_scores({"neuml": {"A01": 0.5, "B01": 0.25}}, qs) == {"A": [0.5], "B": [0.25], "C": []}


def test_exact_doc_ids_follows_the_store_semantics():
    docs = pl.DataFrame({
        "doc_id": ["v1", "v2", "v3", "g1"], "doc_type": ["variant", "variant", "variant", "gene"],
        "gene_symbol": ["BRCA1", "BRCA1", "TP53", "BRCA1"], "rs_dbsnp": [7, 7, None, 7],
        "hgvs_c": [None, None, "c.1A>G", None], "hgvs_p": [None] * 4,
    }, schema_overrides={"rs_dbsnp": pl.Int64, "hgvs_c": pl.Utf8, "hgvs_p": pl.Utf8})

    assert exact_doc_ids(docs, Identifiers((7,), (), (), (), ())) == {"v1", "v2"}
    assert exact_doc_ids(docs, Identifiers((), ("c.1A>G",), (), ("BRCA1",), ())) == set()
    assert exact_doc_ids(docs, Identifiers((), ("c.1A>G",), (), ("TP53",), ())) == {"v3"}


def _manifest(**over):
    base = {"questions_sha256": "q", "prompt_version": "p1", "k": 10, "profile": "a", "mode": "full",
            "exact": False, "model": "m", "provider_tag": "t", "embedding_fingerprint": "f"}
    return {**base, **over}


def test_check_run_manifest_accepts_a_consistent_run_and_refuses_the_rest():
    ok = dict(questions_sha="q", prompt_version="p1", k=10)
    check_run_manifest("a__full", _manifest(), **ok)
    check_run_manifest("a__similarity__exact", _manifest(mode="similarity", exact=True), **ok)
    for name, manifest in [("a__full", _manifest(questions_sha256="x")), ("a__full", _manifest(prompt_version="p0")),
                           ("a__full", _manifest(k=5)), ("b__full", _manifest()),
                           ("a__filters", _manifest()), ("a__full__exact", _manifest())]:
        with pytest.raises(SystemExit):
            check_run_manifest(name, manifest, **ok)


def test_check_runs_consistency():
    check_runs_consistency({"a__full": _manifest(), "a__filters": _manifest(mode="filters")})
    with pytest.raises(SystemExit):
        check_runs_consistency({"a__full": _manifest(), "b__full": _manifest(profile="b", embedding_fingerprint="g")})
    with pytest.raises(SystemExit):
        check_runs_consistency({"a__full": _manifest(), "a__filters": _manifest(mode="filters", model="autre")})


def test_check_complete_field():
    check_complete_field({"a", "b"}, {"a", "b"})
    with pytest.raises(SystemExit, match="b"):
        check_complete_field({"a"}, {"a", "b"})
