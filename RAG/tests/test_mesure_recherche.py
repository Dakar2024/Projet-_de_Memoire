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


def test_exact_doc_ids_ignores_hgvs_when_only_an_out_of_panel_gene_is_cited():
    docs = pl.DataFrame({
        "doc_id": ["v1", "v3"], "doc_type": ["variant", "variant"], "gene_symbol": ["BRCA1", "TP53"],
        "rs_dbsnp": [7, None], "hgvs_c": [None, "c.1A>G"], "hgvs_p": [None, None],
    }, schema_overrides={"rs_dbsnp": pl.Int64, "hgvs_c": pl.Utf8, "hgvs_p": pl.Utf8})

    assert exact_doc_ids(docs, Identifiers((), ("c.1A>G",), (), (), ("MLH1",))) == set()
    assert exact_doc_ids(docs, Identifiers((7,), ("c.1A>G",), (), (), ("MLH1",))) == {"v1"}


def _manifest(**over):
    base = {"questions_sha256": "q", "prompt_version": "p1", "prompt_sha256": "s1", "k": 10, "profile": "a", "mode": "full",
            "approx": False, "model": "m", "provider_tag": "t", "embedding_fingerprint": "f",
            "config_sha256": "c"}
    return {**base, **over}


def test_check_run_manifest_accepts_a_consistent_run_and_refuses_the_rest():
    ok = dict(questions_sha="q", prompt_version="p1", prompt_sha="s1", k=10)
    check_run_manifest("a__full", _manifest(), **ok)
    check_run_manifest("a__similarity__approx", _manifest(mode="similarity", approx=True), **ok)
    for name, manifest in [("a__full", _manifest(questions_sha256="x")), ("a__full", _manifest(prompt_version="p0")),
                           ("a__full", _manifest(prompt_sha256="s0")),
                           ("a__full", _manifest(k=5)), ("b__full", _manifest()),
                           ("a__filters", _manifest()), ("a__full__approx", _manifest()), ("a__similarity__approx", _manifest(mode="similarity")),
                           ("a__similarity", _manifest(mode="similarity", approx=True))]:
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


def test_check_index_matches_truth():
    from RAG.experiments.mesure_recherche import check_index_matches_truth

    check_index_matches_truth({"a__full": _manifest(index_doc_ids_sha256="h"),
                               "a__filters": _manifest(index_doc_ids_sha256="h")}, "h")
    with pytest.raises(SystemExit, match="entre les mesures"):
        check_index_matches_truth({"a__full": _manifest(index_doc_ids_sha256="h"),
                                   "a__filters": _manifest(index_doc_ids_sha256="g")}, "h")
    with pytest.raises(SystemExit, match="vérité terrain"):
        check_index_matches_truth({"a__full": _manifest(index_doc_ids_sha256="g")}, "h")
    with pytest.raises(SystemExit, match="a__full"):
        check_index_matches_truth({"a__full": _manifest()}, "h")


def test_part2_is_not_won_by_chance_through_similarity():
    """Un document pertinent en tête ne compte que s'il vient de la correspondance exacte."""
    q = {"part": 2}

    assert score_question(q, ["clinvar:1"], [], {}, {"clinvar:1"}, K, stages=["exact"]) == 1.0
    assert score_question(q, ["clinvar:1"], [], {}, {"clinvar:1"}, K, stages=["similarity"]) == 0.0
    assert score_question(q, ["clinvar:1"], [], {}, {"clinvar:1"}, K, stages=["filtered"]) == 0.0
    assert score_question(q, ["clinvar:1"], ["identifier_not_found"], {}, {"clinvar:1"}, K) == 0.0
    assert score_question(q, ["clinvar:1"], ["identifier_not_found"], {}, {"clinvar:1"}, K,
                          stages=["exact"]) == 0.0


def test_check_complete_field_refuses_an_extra_profile():
    """Une série « full » d'un profil retiré de la configuration est un fichier périmé :
    elle participerait au choix du modèle."""
    with pytest.raises(SystemExit, match="ancien"):
        check_complete_field({"a", "b", "ancien"}, {"a", "b"})


def test_check_runs_consistency_requires_the_same_configuration():
    check_runs_consistency({"a__full": _manifest(), "b__full": _manifest(profile="b")})
    with pytest.raises(SystemExit, match="configuration"):
        check_runs_consistency({"a__full": _manifest(), "b__full": _manifest(profile="b", config_sha256="d")})
    with pytest.raises(SystemExit, match="configuration"):
        check_runs_consistency({"a__full": _manifest(), "b__full": {**_manifest(profile="b"), "config_sha256": None}})


def test_config_sha256_covers_search_and_llm_but_not_the_chosen_profile():
    from RAG.experiments.mesure_recherche import config_sha256

    raw = {"embedding": {"x": 1}, "search": {"k": 10},
           "llm": {"analysis_profile": "a", "max_tokens": 2000, "profiles": {"a": {"model": "m"}}}}
    reference = config_sha256(raw)

    assert config_sha256({**raw, "embedding": {"x": 2}}) == reference
    assert config_sha256({**raw, "llm": {**raw["llm"], "analysis_profile": "b"}}) == reference
    assert config_sha256({**raw, "search": {"k": 5}}) != reference
    assert config_sha256({**raw, "llm": {**raw["llm"], "max_tokens": 4000}}) != reference
    assert raw["llm"]["analysis_profile"] == "a"


def test_a_provider_mismatch_stops_the_measurement_at_once():
    from RAG.experiments.mesure_recherche import check_analysis_failure

    check_analysis_failure("P1-A01", {"available": True, "error": None}, "claude")
    check_analysis_failure("P1-A01", {"available": False, "error": "LlmUnavailableError: 503"}, "claude")
    with pytest.raises(SystemExit, match="provider_name") as excinfo:
        check_analysis_failure("P1-A01", {"available": False,
                                          "error": "LlmProviderMismatchError: servi par « Amazon »"}, "claude")
    assert "claude" in str(excinfo.value) and "P1-A01" in str(excinfo.value)


def test_a_permanent_error_is_reported_without_traceback():
    from RAG.experiments.mesure_recherche import permanent_error_exit
    from RAG.src.utils.errors import LlmPermanentError, LlmTruncatedError

    truncated = permanent_error_exit(LlmTruncatedError("augmenter llm.max_tokens", cost_usd=0.012))
    refused = permanent_error_exit(LlmPermanentError("OpenRouter refuse la requête (401)"))
    unknown = permanent_error_exit(LlmTruncatedError("augmenter llm.max_tokens"))

    assert isinstance(truncated, SystemExit)
    assert "LlmTruncatedError" in str(truncated.code) and "llm.max_tokens" in str(truncated.code)
    assert "0.012" in str(truncated.code) and "inconnu" in str(unknown.code)
    assert "401" in str(refused.code)


def test_v0_scores_refuses_e1_scores_without_the_neuml_model():
    with pytest.raises(SystemExit, match="neuml"):
        v0_scores({"biobert": {"A01": 0.5}}, [{"id": "P1-A01", "part": 1, "family": "A"}])


def test_load_v0_scores_tolerates_a_missing_e1_file(tmp_path):
    import json

    from RAG.experiments.mesure_recherche import load_v0_scores

    qs = [{"id": "P1-A01", "part": 1, "family": "A"}]
    assert load_v0_scores(tmp_path / "absent.json", qs) is None
    path = tmp_path / "scores.json"
    path.write_text(json.dumps({"neuml": {"A01": 0.5}}), encoding="utf-8")
    assert load_v0_scores(path, qs) == {"A": [0.5], "B": [], "C": []}
    path.write_text(json.dumps({"autre": {}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="neuml"):
        load_v0_scores(path, qs)


def test_config_sha256_ignores_trial_profiles():
    """Les séries officielles ne dépendent pas des essais."""
    from RAG.experiments.mesure_recherche import config_sha256

    raw = {"search": {"k": 10}, "llm": {"analysis_profile": "a", "profiles": {"a": {"model": "m"}}}}
    with_trial = {**raw, "llm": {**raw["llm"], "trial_profiles": {"essai": {"model": "m", "backend": "groq"}}}}

    assert config_sha256(with_trial) == config_sha256(raw)
    assert "trial_profiles" in with_trial["llm"]


# --- Essai gratuit (Groq) : séparé de la mesure officielle ------------------------------

TRIAL_PROFILE = "essai-groq-gpt-oss-120b"


def _dirs(tmp_path, monkeypatch):
    import RAG.experiments.mesure_recherche as m

    monkeypatch.setattr(m, "OUT", tmp_path / "e2a")
    monkeypatch.setattr(m, "OUT_ESSAI", tmp_path / "e2a-essai")
    monkeypatch.setattr(m, "E1_SCORES_PATH", tmp_path / "absent.json")
    return m


def test_output_dir_separates_trial_and_official_runs(tmp_path, monkeypatch):
    from RAG.src.utils.config import load_search_config

    m = _dirs(tmp_path, monkeypatch)

    assert m.output_dir(load_search_config(profile=TRIAL_PROFILE)) == tmp_path / "e2a-essai"
    assert m.output_dir(load_search_config(profile="groq-gpt-oss-120b")) == tmp_path / "e2a"


class _FakeSearcher:
    instances: list = []

    def __init__(self, *, profile_name, cache_path):
        from RAG.src.utils.config import load_search_config

        self.config = load_search_config(profile=profile_name)
        self.cache_path = cache_path
        _FakeSearcher.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def index_doc_ids_sha256(self):
        return "h"

    def search(self, question, mode, force_exact):
        class Result:
            def as_dict(self):
                return {"documents": [{"doc_id": "d", "stage": "similarity"}],
                        "trace": {"flags": [], "identifiers": {}, "timings_ms": {},
                                  "analysis": {"available": True, "error": None}}}
        return Result()


@pytest.mark.parametrize("profile, folder", [(TRIAL_PROFILE, "e2a-essai"), ("groq-gpt-oss-120b", "e2a")])
def test_mesurer_writes_trial_runs_apart_from_official_ones(tmp_path, monkeypatch, profile, folder):
    import argparse

    import RAG.src.retrieval.retriever as retriever

    m = _dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "Searcher", _FakeSearcher)
    _FakeSearcher.instances.clear()

    m.cmd_mesurer(argparse.Namespace(profile=profile, mode="full", approx=False))

    assert _FakeSearcher.instances[0].cache_path == tmp_path / folder / "cache_analyses.json"
    assert [p.name for p in (tmp_path / folder / "runs").iterdir()] == [f"{profile}__full.json"]
    other = "e2a" if folder == "e2a-essai" else "e2a-essai"
    assert not (tmp_path / other).exists()


def _perfect_run(profile, mode, questions, *, broken_part2=False):
    from RAG.src.prompts.analysis import PROMPT_SHA, PROMPT_VERSION

    results = {}
    for q in questions:
        part3 = q["part"] == 3
        stages = ["exact"] if q["part"] == 2 else ["similarity"]
        if broken_part2 and q["part"] == 2:
            stages = ["similarity"]
        results[q["id"]] = {
            "doc_ids": [] if part3 else [f"d-{q['id']}"], "stages": stages,
            "flags": list(q.get("expected_flags", [])) if part3 else [],
            "identifiers": dict(q.get("expected_identifiers", {})) if part3 else {},
            "analysis": {"significance": q["expected_significance"], "latency_ms": 12.0, "cost_usd": 0.0},
            "timings_ms": {}}
    manifest = {"questions_sha256": m_sha(), "profile": profile, "model": "openai/gpt-oss-120b",
                "provider_tag": "groq", "prompt_version": PROMPT_VERSION, "prompt_sha256": PROMPT_SHA,
                "mode": mode, "approx": False, "k": 10, "embedding_fingerprint": "f", "config_sha256": "c",
                "index_doc_ids_sha256": "h"}
    return {"manifest": manifest, "results": results}


def m_sha():
    from RAG.experiments.mesure_recherche import QUESTIONS_PATH, _sha256

    return _sha256(QUESTIONS_PATH)


def _write_trial_field(tmp_path, *, profile=TRIAL_PROFILE, broken_part2=False):
    import json

    from RAG.experiments.mesure_recherche import _load_questions

    questions = _load_questions()
    truth = {"manifest": {"questions_sha256": m_sha(), "gold_doc_ids_sha256": "h"},
             "relevant": {q["id"]: ([] if q["part"] == 3 else [f"d-{q['id']}"]) for q in questions}}
    (tmp_path / "e2a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "e2a" / "verite_terrain.json").write_text(json.dumps(truth), encoding="utf-8")
    runs = tmp_path / "e2a-essai" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for mode in ("similarity", "filters", "full"):
        run = _perfect_run(profile, mode, questions, broken_part2=broken_part2 and mode == "full")
        (runs / f"{profile}__{mode}.json").write_text(json.dumps(run), encoding="utf-8")


def test_evaluer_essai_reports_without_choosing_a_model(tmp_path, monkeypatch, capsys):
    import argparse
    import re

    m = _dirs(tmp_path, monkeypatch)
    _write_trial_field(tmp_path)
    (tmp_path / "e2a" / "runs").mkdir()
    (tmp_path / "e2a" / "runs" / "illisible.json").write_text("pas du json", encoding="utf-8")

    m.cmd_evaluer_essai(argparse.Namespace(essai=True))

    out = capsys.readouterr().out
    assert "Essai de validation de la chaîne — ne sert pas au choix du modèle" in out
    assert "Décision" not in out and "Choix du modèle" not in out
    assert re.search(rf"- {TRIAL_PROFILE} : (\d+)/\1 OK", out)
    assert "V3 complète" in out and "V1 similarité" in out
    assert "1.000" in out


def test_check_run_manifest_refuses_old_format_and_missing_keys_cleanly():
    ok = dict(questions_sha="q", prompt_version="p1", prompt_sha="s1", k=10)
    old = _manifest()
    old["exact"] = old.pop("approx")
    with pytest.raises(SystemExit, match=r"a__full.*ancien format \(champ exact\)"):
        check_run_manifest("a__full", old, **ok)
    incomplete = _manifest()
    del incomplete["embedding_fingerprint"]
    with pytest.raises(SystemExit, match="a__full.*embedding_fingerprint"):
        check_run_manifest("a__full", incomplete, **ok)


def test_recall_diagnostic_is_not_computable_without_any_exact_result(tmp_path, monkeypatch, capsys):
    import json

    m = _dirs(tmp_path, monkeypatch)
    _write_trial_field(tmp_path)
    runs = tmp_path / "e2a-essai" / "runs"
    run = json.loads((runs / f"{TRIAL_PROFILE}__similarity.json").read_text(encoding="utf-8"))
    for r in run["results"].values():
        r["doc_ids"] = []
    questions = m._load_questions()
    loaded = {f"{TRIAL_PROFILE}__similarity": run, f"{TRIAL_PROFILE}__similarity__approx": run}

    m._print_ablation(TRIAL_PROFILE, {}, loaded, questions)

    assert "= non calculable" in capsys.readouterr().out


@pytest.mark.parametrize("approx_doc, expected", [(None, "1.000"), ("zzz", "0.000")])
def test_evaluer_essai_prints_the_hnsw_recall_against_exact_search(tmp_path, monkeypatch, capsys, approx_doc, expected):
    import argparse
    import json

    m = _dirs(tmp_path, monkeypatch)
    _write_trial_field(tmp_path)
    runs = tmp_path / "e2a-essai" / "runs"
    run = json.loads((runs / f"{TRIAL_PROFILE}__similarity.json").read_text(encoding="utf-8"))
    run["manifest"]["approx"] = True
    if approx_doc:
        for r in run["results"].values():
            r["doc_ids"] = [approx_doc] if r["doc_ids"] else []
    (runs / f"{TRIAL_PROFILE}__similarity__approx.json").write_text(json.dumps(run), encoding="utf-8")

    m.cmd_evaluer_essai(argparse.Namespace(essai=True))

    assert ("Diagnostic : rappel moyen de l'index HNSW (ef_search 40) par rapport à la recherche exacte = "
            + expected) in capsys.readouterr().out


def test_mesurer_approx_forces_the_hnsw_search_and_names_the_run(tmp_path, monkeypatch):
    import argparse
    import json

    import RAG.src.retrieval.retriever as retriever

    class Spy(_FakeSearcher):
        forced = []

        def search(self, question, mode, force_exact):
            Spy.forced.append(force_exact)
            return super().search(question, mode, force_exact)

    m = _dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "Searcher", Spy)

    m.cmd_mesurer(argparse.Namespace(profile=TRIAL_PROFILE, mode="similarity", approx=True))
    m.cmd_mesurer(argparse.Namespace(profile=TRIAL_PROFILE, mode="similarity", approx=False))

    assert set(Spy.forced[: len(Spy.forced) // 2]) == {False} and set(Spy.forced[len(Spy.forced) // 2:]) == {None}
    runs = tmp_path / "e2a-essai" / "runs"
    assert sorted(p.name for p in runs.iterdir()) == [f"{TRIAL_PROFILE}__similarity.json",
                                                      f"{TRIAL_PROFILE}__similarity__approx.json"]
    manifest = json.loads((runs / f"{TRIAL_PROFILE}__similarity__approx.json").read_text(encoding="utf-8"))["manifest"]
    assert manifest["approx"] is True and "exact" not in manifest


def test_evaluer_essai_shows_everything_then_fails_on_part2(tmp_path, monkeypatch, capsys):
    import argparse

    m = _dirs(tmp_path, monkeypatch)
    _write_trial_field(tmp_path, broken_part2=True)

    with pytest.raises(SystemExit, match="partie 2"):
        m.cmd_evaluer_essai(argparse.Namespace(essai=True))
    out = capsys.readouterr().out
    assert "ÉCHEC" in out and "V3 complète" in out and "Décision" not in out


def test_evaluer_essai_refuses_an_official_profile_among_trial_runs(tmp_path, monkeypatch):
    import argparse

    m = _dirs(tmp_path, monkeypatch)
    _write_trial_field(tmp_path, profile="gpt-oss-120b")

    with pytest.raises(SystemExit, match="gpt-oss-120b"):
        m.cmd_evaluer_essai(argparse.Namespace(essai=True))


def test_official_evaluer_ignores_trial_runs(tmp_path, monkeypatch):
    import argparse

    m = _dirs(tmp_path, monkeypatch)
    _write_trial_field(tmp_path)

    with pytest.raises(SystemExit, match="aucune mesure dans data/experiments/e2a/runs"):
        m.cmd_evaluer(argparse.Namespace(essai=False))


def test_evaluer_dispatches_on_the_essai_flag(monkeypatch):
    import RAG.experiments.mesure_recherche as m

    calls = []
    monkeypatch.setattr(m, "cmd_evaluer", lambda args: calls.append("officiel"))
    monkeypatch.setattr(m, "cmd_evaluer_essai", lambda args: calls.append("essai"))

    m.main(["evaluer"])
    m.main(["evaluer", "--essai"])

    assert calls == ["officiel", "essai"]


def test_an_exhausted_quota_stops_the_measurement_at_once():
    """Sans cet arrêt, chaque question restante attendrait encore les 429 pour rien."""
    from RAG.experiments.mesure_recherche import check_analysis_failure

    with pytest.raises(SystemExit, match="quota Groq épuisé") as excinfo:
        check_analysis_failure("P1-B03", {"available": False,
                                          "error": "LlmQuotaExhaustedError: quota Groq épuisé (429)"}, "essai")
    assert "P1-B03" in str(excinfo.value) and "cache" in str(excinfo.value)


def test_mesurer_stops_at_the_first_exhausted_quota(tmp_path, monkeypatch):
    import argparse

    import RAG.src.retrieval.retriever as retriever

    class QuotaSearcher(_FakeSearcher):
        searched = 0

        def search(self, question, mode, force_exact):
            QuotaSearcher.searched += 1

            class Result:
                def as_dict(self):
                    return {"documents": [], "trace": {"flags": [], "identifiers": {}, "timings_ms": {},
                            "analysis": {"available": False,
                                         "error": "LlmQuotaExhaustedError: quota Groq épuisé (429)"}}}
            return Result()

    m = _dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "Searcher", QuotaSearcher)

    with pytest.raises(SystemExit, match="quota Groq épuisé"):
        m.cmd_mesurer(argparse.Namespace(profile=TRIAL_PROFILE, mode="full", approx=False))
    assert QuotaSearcher.searched == 1
    assert not (tmp_path / "e2a-essai" / "runs").exists()


def test_config_sha256_ignores_generation_and_api_settings():
    import yaml

    from RAG.experiments.mesure_recherche import config_sha256
    from RAG.src.utils.config import DEFAULT_CONFIG_PATH

    base = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    other = (base.replace("generation_max_tokens: 3000", "generation_max_tokens: 4000")
                 .replace("max_concurrency: 4", "max_concurrency: 2")
                 .replace("generation_profile: essai-groq-gpt-oss-120b", "generation_profile: x"))
    assert other != base

    assert config_sha256(yaml.safe_load(base)) == config_sha256(yaml.safe_load(other))
