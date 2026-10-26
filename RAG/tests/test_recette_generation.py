import json
from types import SimpleNamespace

import pytest

from RAG.experiments import recette_generation as rg
from RAG.experiments.recette_generation import CachedGenerator, ThrottleMeter, score_recette, summarize
from RAG.src.llm.common import LlmCall


@pytest.fixture(autouse=True)
def _empty_control_set(tmp_path_factory, monkeypatch):
    """Série de contrôle vide par défaut : les tests ne lisent jamais le vrai fichier."""
    path = tmp_path_factory.mktemp("controle") / "controle.yaml"
    path.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(rg, "QUESTIONS_CONTROL", path)


def rec(status="answered", citations=("clinvar:1",), rejected=None, reason=None, total=3000.0):
    return {"status": status, "citations": list(citations), "rejected": rejected, "scope_reason": reason,
            "timings_ms": {"total": total}}


def test_part2_needs_answered_with_a_relevant_citation():
    q = {"part": 2}
    assert score_recette(q, rec(), {"clinvar:1"})["ok"] is True
    assert score_recette(q, rec(citations=("clinvar:2",)), {"clinvar:1"})["ok"] is False
    assert score_recette(q, rec(status="unverifiable"), {"clinvar:1"})["ok"] is False


def test_part1_has_no_threshold():
    assert score_recette({"part": 1}, rec(), set())["ok"] is None


def test_part3_traps_need_a_fixed_message_status():
    q = {"part": 3, "expected_flags": ["identifier_not_found"]}
    assert score_recette(q, rec(status="not_in_sources", citations=()), set())["ok"] is True
    assert score_recette(q, rec(status="answered"), set())["ok"] is False


def test_part3_trap_without_flag_only_forbids_unverifiable():
    q = {"part": 3, "expected_flags": []}
    assert score_recette(q, rec(), set())["ok"] is True
    assert score_recette(q, rec(status="unverifiable"), set())["ok"] is False


def test_part4_needs_the_expected_reason():
    q = {"part": 4, "expected_scope_reason": "counting"}
    assert score_recette(q, rec(status="out_of_scope", citations=(), reason="counting"), set())["ok"] is True
    assert score_recette(q, rec(status="out_of_scope", citations=(), reason="acmg"), set())["ok"] is False


def test_summary_reports_thresholds_rejections_and_latency():
    records = [dict(rec(total=t), part=2, ok=True) for t in (1000.0, 2000.0, 3000.0, 4000.0)]
    records.append(dict(rec(status="unverifiable", rejected="identifier_not_in_sources"), part=1, ok=None))
    s = summarize(records)
    assert s["part2"] == (4, 4) and s["rejections"] == {"identifier_not_in_sources": 1}
    assert s["latency_ms"]["median"] == 3000.0 and s["latency_ms"]["p95"] >= 3000.0


def test_summary_excludes_cache_replays_from_latency():
    records = [dict(rec(total=100.0), part=2, ok=True, from_cache=True),
               dict(rec(total=5000.0), part=2, ok=True, from_cache=False)]
    s = summarize(records)
    assert s["latency_ms"]["median"] == 5000.0 and s["n_cached"] == 1


class FakeInner:
    def __init__(self):
        self.calls, self.closed = 0, False

    def complete_json(self, profile, *, system, user, schema_name, schema, max_tokens):
        self.calls += 1
        return LlmCall(content={"n": self.calls}, generation_id="g", provider_name="p", cost_usd=0.1,
                       prompt_tokens=1, completion_tokens=2)

    def close(self):
        self.closed = True


PROFILE = SimpleNamespace(model="m", provider_tag="t")


def call(gen, user="u"):
    return gen.complete_json(PROFILE, system="s", user=user, schema_name="n", schema={}, max_tokens=10)


def test_cache_replays_without_calling_the_llm_and_survives_restart(tmp_path):
    path = tmp_path / "cache.json"
    inner = FakeInner()
    gen = CachedGenerator(inner, path, "sha")
    first = call(gen)
    assert gen.last_hit is False and inner.calls == 1
    again = call(gen)
    assert gen.last_hit is True and inner.calls == 1 and again == first
    reopened = CachedGenerator(FakeInner(), path, "sha")
    assert call(reopened) == first and reopened.last_hit is True


def test_cache_key_depends_on_prompt_sha_and_user_message(tmp_path):
    path = tmp_path / "cache.json"
    inner = FakeInner()
    call(CachedGenerator(inner, path, "sha1"))
    call(CachedGenerator(inner, path, "sha2"))
    call(CachedGenerator(inner, path, "sha1"), user="other")
    assert inner.calls == 3


def test_cache_does_not_store_failures_and_close_delegates(tmp_path):
    class Boom(FakeInner):
        def complete_json(self, *a, **k):
            raise RuntimeError("x")

    path = tmp_path / "cache.json"
    gen = CachedGenerator(Boom(), path, "sha")
    with pytest.raises(RuntimeError):
        call(gen)
    assert not path.exists()
    inner = FakeInner()
    CachedGenerator(inner, path, "sha").close()
    assert inner.closed is True


def test_missing_out_of_scope_questions_file_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "QUESTIONS_E2B", tmp_path / "absent.yaml")
    with pytest.raises(SystemExit, match="absent"):
        rg._load_questions()


def test_evaluer_refuses_to_conclude_when_questions_are_missing(tmp_path, monkeypatch):
    qa, qb = tmp_path / "a.yaml", tmp_path / "b.yaml"
    qa.write_text("- {id: P2-01, part: 2, question: q}\n", encoding="utf-8")
    qb.write_text("- {id: P4-01, part: 4, question: q, expected_scope_reason: counting}\n", encoding="utf-8")
    monkeypatch.setattr(rg, "QUESTIONS_E2A", qa)
    monkeypatch.setattr(rg, "QUESTIONS_E2B", qb)
    monkeypatch.setattr(rg, "OUT", tmp_path)
    (tmp_path / "records.json").write_text(json.dumps([dict(rec(), id="P2-01", part=2)]), encoding="utf-8")
    with pytest.raises(SystemExit, match="P4-01"):
        rg.cmd_evaluer(None)


def _result(available=True, from_llm=True, analysis_ms=900.0):
    analysis = SimpleNamespace(available=available, latency_ms=analysis_ms, from_cache=True)
    answer = SimpleNamespace(status="answered", scope_reason=None, sources=[SimpleNamespace(doc_id="d")],
                             rejected=None, answer="t", from_llm=from_llm)
    return SimpleNamespace(answer=answer, search=SimpleNamespace(trace=SimpleNamespace(analysis=analysis, flags=["f"])),
                           timings_ms={"analysis": 0.0, "total": 2000.0})


def test_record_keeps_analysis_fields_and_replay_flag():
    r = rg.build_record({"id": "q", "part": 2}, _result(), replayed=False)
    assert r["analysis_latency_ms"] == 900.0 and r["analysis_available"] is True and r["flags"] == ["f"]
    assert r["generation_from_llm"] is True and r["from_cache"] is False


def test_summary_uses_original_analysis_latency_and_splits_fixed_messages():
    llm = dict(rec(total=2000.0), part=2, ok=True, timings_ms={"total": 2000.0, "analysis": 0.0},
               analysis_latency_ms=900.0, generation_from_llm=True)
    fixed = dict(llm, generation_from_llm=False, analysis_latency_ms=100.0)
    s = summarize([llm, fixed])
    assert s["latency_ms"]["median"] == 2900.0 and s["latency_fixed_ms"]["median"] == 2100.0


def test_cache_key_depends_on_max_tokens(tmp_path):
    inner = FakeInner()
    gen = CachedGenerator(inner, tmp_path / "c.json", "sha")
    gen.complete_json(PROFILE, system="s", user="u", schema_name="n", schema={}, max_tokens=10)
    gen.complete_json(PROFILE, system="s", user="u", schema_name="n", schema={}, max_tokens=20)
    assert inner.calls == 2


def test_evaluer_refuses_degraded_analysis(tmp_path, monkeypatch):
    qa, qb = tmp_path / "a.yaml", tmp_path / "b.yaml"
    qa.write_text("- {id: P2-01, part: 2, question: q}\n", encoding="utf-8")
    qb.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(rg, "QUESTIONS_E2A", qa)
    monkeypatch.setattr(rg, "QUESTIONS_E2B", qb)
    monkeypatch.setattr(rg, "OUT", tmp_path)
    (tmp_path / "records.json").write_text(
        json.dumps([dict(rec(), id="P2-01", part=2, analysis_available=False)]), encoding="utf-8")
    with pytest.raises(SystemExit, match="P2-01"):
        rg.cmd_evaluer(None)


class _Pipeline:
    def __init__(self, results, searcher_sha="x"):
        self.results, self.slot = list(results), SimpleNamespace(
            generator=FakeInner(), searcher=SimpleNamespace(index_doc_ids_sha256=lambda: searcher_sha))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def acquire(self):
        return self.slot

    def release(self, slot):
        pass

    def ask(self, slot, question):
        # Premier tour : appel réel (remplit last_hit), puis message fixe sans appel.
        res = self.results.pop(0)
        if res.answer.from_llm:
            call(slot.generator)
        return res


def _setup_lancer(monkeypatch, tmp_path, results, sha="x"):
    import RAG.src.generation.pipeline as pl
    qa, qb = tmp_path / "a.yaml", tmp_path / "b.yaml"
    qa.write_text("- {id: Q1, part: 2, question: a}\n- {id: Q2, part: 3, question: b}\n- {id: Q3, part: 3, question: c}\n", encoding="utf-8")
    qb.write_text("[]\n", encoding="utf-8")
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"manifest": {"gold_doc_ids_sha256": sha}, "relevant": {}}), encoding="utf-8")
    for name, value in (("QUESTIONS_E2A", qa), ("QUESTIONS_E2B", qb), ("OUT", tmp_path), ("TRUTH_PATH", truth)):
        monkeypatch.setattr(rg, name, value)
    monkeypatch.setattr(pl, "QuestionPipeline", lambda *a, **k: _Pipeline(results))


def test_fixed_message_after_a_cache_hit_is_not_a_replay(tmp_path, monkeypatch):
    (tmp_path / "cache_generation.json").write_text("{}", encoding="utf-8")
    _setup_lancer(monkeypatch, tmp_path, [_result(), _result(), _result(from_llm=False)])
    # Q2 rejoue le cache de Q1 (même message) ; Q3 est à message fixe juste après ce rejeu.
    rg.cmd_lancer(None)
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))
    assert [r["from_cache"] for r in records] == [False, True, False]


def test_degraded_analysis_is_not_recorded_and_stops(tmp_path, monkeypatch):
    _setup_lancer(monkeypatch, tmp_path, [_result(available=False)])
    with pytest.raises(SystemExit) as exc:
        rg.cmd_lancer(None)
    assert exc.value.code == 1 and not (tmp_path / "records.json").exists()


def test_lancer_stops_when_index_differs_from_truth(tmp_path, monkeypatch):
    _setup_lancer(monkeypatch, tmp_path, [_result()], sha="autre")
    with pytest.raises(SystemExit, match="vérité terrain"):
        rg.cmd_lancer(None)


def test_unavailable_generation_fails_parts_2_3_4_even_for_a_trap_without_flag():
    unavailable = rec(status="generation_unavailable", citations=())
    assert score_recette({"part": 2}, unavailable, {"clinvar:1"})["ok"] is False
    assert score_recette({"part": 3, "expected_flags": []}, unavailable, set())["ok"] is False
    assert score_recette({"part": 3, "expected_flags": ["identifier_not_found"]}, unavailable, set())["ok"] is False
    assert score_recette({"part": 4, "expected_scope_reason": "counting"}, unavailable, set())["ok"] is False
    assert score_recette({"part": 1}, unavailable, set())["ok"] is None


def test_summary_counts_unavailable_generations_without_touching_latency():
    ok = dict(rec(total=2000.0), part=2, ok=True, timings_ms={"total": 2000.0, "analysis": 0.0},
              analysis_latency_ms=900.0, generation_from_llm=True)
    down = {"id": "q", "part": 2, "status": "generation_unavailable", "ok": False, "citations": [],
            "rejected": None, "from_cache": False}
    s = summarize([ok, down])
    assert s["statuses"] == {"answered": 1, "generation_unavailable": 1}
    assert s["part2"] == (1, 2) and s["latency_ms"]["n"] == 1 and s["n_cached"] == 0


def test_record_carries_the_prompt_version():
    from RAG.src.prompts.generation import GENERATION_PROMPT_VERSION
    r = rg.build_record({"id": "q", "part": 2}, _result(), replayed=False)
    assert r["prompt_version"] == GENERATION_PROMPT_VERSION


def test_evaluer_refuses_records_from_several_prompt_versions(tmp_path, monkeypatch):
    qa, qb = tmp_path / "a.yaml", tmp_path / "b.yaml"
    qa.write_text("- {id: P2-01, part: 2, question: q}\n- {id: P2-02, part: 2, question: q}\n", encoding="utf-8")
    qb.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(rg, "QUESTIONS_E2A", qa)
    monkeypatch.setattr(rg, "QUESTIONS_E2B", qb)
    monkeypatch.setattr(rg, "OUT", tmp_path)
    (tmp_path / "records.json").write_text(json.dumps([
        dict(rec(), id="P2-01", part=2, prompt_version="generation-v4"),
        dict(rec(), id="P2-02", part=2, prompt_version="generation-v5")]), encoding="utf-8")
    with pytest.raises(SystemExit, match="e2b-recette"):
        rg.cmd_evaluer(None)


class _FailingPipeline(_Pipeline):
    def ask(self, slot, question):
        if isinstance(self.results[0], Exception):
            raise self.results.pop(0)
        return super().ask(slot, question)


def test_unavailable_generation_is_recorded_without_text_and_the_run_continues(tmp_path, monkeypatch):
    import RAG.src.generation.pipeline as pl
    from RAG.src.utils.errors import LlmUnavailableError
    _setup_lancer(monkeypatch, tmp_path, [])
    results = [_result(), LlmUnavailableError("texte de la question secrète"), _result()]
    monkeypatch.setattr(pl, "QuestionPipeline", lambda *a, **k: _FailingPipeline(results))
    rg.cmd_lancer(None)
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))
    assert [r["status"] for r in records] == ["answered", "generation_unavailable", "answered"]
    down = records[1]
    assert down["error"] == "LlmUnavailableError" and down["citations"] == []
    assert "secrète" not in json.dumps(down) and down["prompt_version"]


def test_quota_exhaustion_still_stops_the_run(tmp_path, monkeypatch):
    import RAG.src.generation.pipeline as pl
    from RAG.src.utils.errors import LlmQuotaExhaustedError
    _setup_lancer(monkeypatch, tmp_path, [])
    results = [_result(), LlmQuotaExhaustedError("quota")]
    monkeypatch.setattr(pl, "QuestionPipeline", lambda *a, **k: _FailingPipeline(results))
    with pytest.raises(SystemExit) as exc:
        rg.cmd_lancer(None)
    assert exc.value.code == 1
    assert [r["id"] for r in json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))] == ["Q1"]


# --- vague finale : attentes de limite de débit, série de contrôle, rejeu ---

def test_throttle_meter_measures_wrapped_sleeps_only():
    ticks = iter([0.0, 2.5, 10.0, 10.5])
    meter = ThrottleMeter(clock=lambda: next(ticks))
    slept = []
    client = SimpleNamespace(_sleep=slept.append)
    assert meter.install(client) is True and meter.install(SimpleNamespace()) is False and meter.install(None) is False
    client._sleep(2.0)
    client._sleep(0.5)
    assert slept == [2.0, 0.5] and meter.total_ms == 3000.0
    meter.reset()
    assert meter.total_ms == 0.0


def test_lancer_records_the_throttle_waits_of_each_question(tmp_path, monkeypatch):
    import time as _time

    import RAG.src.generation.pipeline as pl

    class WaitingPipeline(_Pipeline):
        def ask(self, slot, question):
            if question == "a":
                slot.searcher._llm._sleep(0.02)  # attente du client d'analyse
            return super().ask(slot, question)

    _setup_lancer(monkeypatch, tmp_path, [])
    pipeline = WaitingPipeline([_result(), _result(from_llm=False), _result(from_llm=False)])
    pipeline.slot.searcher._llm = SimpleNamespace(_sleep=_time.sleep)
    monkeypatch.setattr(pl, "QuestionPipeline", lambda *a, **k: pipeline)
    rg.cmd_lancer(None)
    records = json.loads((tmp_path / "records.json").read_text(encoding="utf-8"))
    assert records[0]["throttle_wait_ms"] >= 15.0
    assert records[1]["throttle_wait_ms"] == 0.0 and records[2]["throttle_wait_ms"] == 0.0


def test_latency_excludes_throttle_waits_and_flags_older_records_as_upper_bounds():
    base = dict(rec(total=5000.0), part=2, ok=True, timings_ms={"total": 5000.0, "analysis": 0.0},
                analysis_latency_ms=0.0, generation_from_llm=True)
    measured = dict(base, throttle_wait_ms=4000.0)
    s = summarize([measured])
    assert s["latency_ms"]["median"] == 1000.0 and s["latency_with_waits_ms"]["median"] == 5000.0
    assert s["n_upper_bound"] == 0
    assert summarize([measured, base])["n_upper_bound"] == 1


def _write_sets(tmp_path, monkeypatch, e2a="[]\n", dev="[]\n", control="[]\n"):
    paths = {}
    for name, text in (("QUESTIONS_E2A", e2a), ("QUESTIONS_E2B", dev), ("QUESTIONS_CONTROL", control)):
        path = tmp_path / f"{name}.yaml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(rg, name, path)
        paths[name] = path
    return paths


def test_control_set_is_loaded_and_marked(tmp_path, monkeypatch):
    _write_sets(tmp_path, monkeypatch, e2a="- {id: P2-01, part: 2, question: a}\n",
                dev="- {id: P4-01, part: 4, question: b, expected_scope_reason: counting}\n",
                control="- {id: C4-01, part: 4, question: c, expected_scope_reason: acmg}\n")
    questions = {q["id"]: q for q in rg._load_questions()}
    assert questions["P4-01"]["set"] == "developpement" and questions["C4-01"]["set"] == "controle"
    assert "set" not in questions["P2-01"]


def test_missing_control_file_fails_clearly(tmp_path, monkeypatch):
    paths = _write_sets(tmp_path, monkeypatch)
    paths["QUESTIONS_CONTROL"].unlink()
    with pytest.raises(SystemExit, match="contrôle"):
        rg._load_questions()


def test_duplicate_ids_or_foreign_set_in_the_control_file_are_refused(tmp_path, monkeypatch):
    _write_sets(tmp_path, monkeypatch, dev="- {id: P4-01, part: 4, question: b}\n",
                control="- {id: P4-01, part: 4, question: c}\n")
    with pytest.raises(SystemExit, match="double"):
        rg._load_questions()
    _write_sets(tmp_path, monkeypatch, control="- {id: C4-01, part: 4, set: developpement, question: c}\n")
    with pytest.raises(SystemExit, match="série"):
        rg._load_questions()


def test_part4_threshold_counts_the_control_set_only_and_partial_is_counted_for_p2():
    def p4(ok, which):
        return dict(rec(status="out_of_scope", citations=()), part=4, ok=ok, set=which)
    records = [p4(True, "controle"), p4(False, "controle"), p4(True, "developpement"), p4(True, "developpement"),
               dict(rec(status="partial"), part=2, ok=True)]
    s = summarize(records)
    assert s["part4"] == (1, 2) and s["part4_dev"] == (2, 2) and s["part2_partial"] == 1


def _complete_records(ids_parts):
    return [dict(rec(status="out_of_scope", citations=(), reason="counting"), id=i, part=p,
                 analysis_available=True, prompt_version="v", timings_ms={"total": 1.0}, from_cache=True)
            for i, p in ids_parts]


def test_evaluer_reports_control_and_development_sets_apart_and_reads_another_file(tmp_path, monkeypatch, capsys):
    _write_sets(tmp_path, monkeypatch,
                dev="- {id: P4-01, part: 4, question: b, expected_scope_reason: counting}\n",
                control="- {id: C4-01, part: 4, question: c, expected_scope_reason: counting}\n")
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"manifest": {}, "relevant": {}}), encoding="utf-8")
    monkeypatch.setattr(rg, "TRUTH_PATH", truth)
    monkeypatch.setattr(rg, "OUT", tmp_path)
    (tmp_path / "records_v2.json").write_text(json.dumps(_complete_records([("P4-01", 4), ("C4-01", 4)])),
                                              encoding="utf-8")
    rg.main(["evaluer", "--fichier", "records_v2.json"])
    out = capsys.readouterr().out
    assert "série de contrôle) | 1/1 | ≥ 90 % | OK" in out
    assert "développement (ayant servi à écrire les règles) | 1/1" in out


def test_evaluer_without_control_questions_does_not_pass_p4(tmp_path, monkeypatch, capsys):
    _write_sets(tmp_path, monkeypatch, dev="- {id: P4-01, part: 4, question: b, expected_scope_reason: counting}\n")
    truth = tmp_path / "truth.json"
    truth.write_text(json.dumps({"manifest": {}, "relevant": {}}), encoding="utf-8")
    monkeypatch.setattr(rg, "TRUTH_PATH", truth)
    monkeypatch.setattr(rg, "OUT", tmp_path)
    (tmp_path / "records.json").write_text(json.dumps(_complete_records([("P4-01", 4)])), encoding="utf-8")
    rg.cmd_evaluer(None)
    assert "série de contrôle) | 0/0 | ≥ 90 % | ÉCHEC" in capsys.readouterr().out


def test_unverifiable_record_cites_nothing_and_keeps_transmitted_sources():
    res = _result()
    res.answer.status = "unverifiable"
    r = rg.build_record({"id": "q", "part": 2}, res, replayed=False)
    assert r["citations"] == [] and r["sources_transmises"] == ["d"]


def test_withheld_not_in_sources_text_is_kept_for_review():
    res = _result()
    res.answer.status, res.answer.sources, res.answer.llm_text_withheld = "not_in_sources", [], "texte retenu"
    assert rg.build_record({"id": "q", "part": 2}, res, replayed=False)["llm_text_withheld"] == "texte retenu"


# Rejeu : vraie chaîne de génération (generate_answer), génération lue d'un cache.

def _replay_setup():
    from RAG.src.generation.answer import generate_answer
    from RAG.src.generation.context import build_context
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA, user_message
    from RAG.tests.test_generation_answer import PROFILE, doc, ok, result

    def res_for(question):
        return result(docs=[doc()], question=question)

    questions = [{"id": "Q1", "part": 2, "question": "Que sait-on de rs80357906 ?"},
                 {"id": "Q2", "part": 4, "question": "Combien de variants pathogènes compte BRCA1 ?"},
                 {"id": "Q3", "part": 2, "question": "Et c.5266dup ?"},
                 {"id": "Q4", "part": 2, "question": "Pas encore posée"}]
    cache = {}
    for q, content in ((questions[0], ok(answer="Le variant rs80357906 n'est pas bénin, il est pathogène.")),
                       (questions[1], ok(answer="Le gène BRCA1 compte 1 variant pathogène."))):
        r = res_for(q["question"])
        user = user_message(q["question"], build_context(list(r.documents)), list(r.trace.flags))
        key = rg.cache_key(GENERATION_PROMPT_SHA, PROFILE, user, 3000)
        cache[key] = {"content": content, "generation_id": "g", "provider_name": "Groq", "cost_usd": 0.0,
                      "prompt_tokens": 1, "completion_tokens": 1}
    client = rg.ReplayClient(cache, GENERATION_PROMPT_SHA)
    v1 = [{"id": q["id"], "part": q["part"], "status": "answered", "citations": ["clinvar:32716"],
           "timings_ms": {"total": 9.0}, "analysis_latency_ms": 5.0} for q in questions[:3]]
    generate = lambda q, r: generate_answer(q, r, client=client, profile=PROFILE, max_tokens=3000)
    return questions, v1, res_for, generate, client


def test_replay_runs_cached_generations_through_the_current_checks_without_network():
    questions, v1, res_for, generate, client = _replay_setup()
    v2 = {r["id"]: r for r in rg.replay_records(questions, v1, search=res_for, generate=generate)}
    assert set(v2) == {"Q1", "Q2", "Q3"}  # Q4 jamais enregistrée : pas de rejeu
    # Q1 : la négation est désormais rejetée ; Q2 : les règles hors périmètre court-circuitent.
    assert (v2["Q1"]["status"], v2["Q1"]["rejected"], v2["Q1"]["citations"]) == (
        "unverifiable", "significance_not_in_sources", [])
    assert (v2["Q2"]["status"], v2["Q2"]["scope_reason"]) == ("out_of_scope", "counting")
    assert v2["Q1"]["replay"] == v2["Q2"]["replay"] == "replayed" and v2["Q1"]["v1_status"] == "answered"
    assert v2["Q1"]["from_cache"] is True and v2["Q1"]["analysis_latency_ms"] == 5.0
    # Q3 : aucune génération en cache pour ces documents, l'enregistrement d'origine est recopié.
    assert (v2["Q3"]["status"], v2["Q3"]["replay"]) == ("answered", "generation_not_cached")
    assert client.calls == 1


def test_replay_keeps_the_original_record_when_the_analysis_is_not_cached():
    questions, v1, res_for, generate, _ = _replay_setup()

    def degraded(question):
        r = res_for(question)
        r.trace.analysis = SimpleNamespace(available=False)
        return r
    v2 = rg.replay_records(questions[:1], v1, search=degraded, generate=generate)
    assert (v2[0]["status"], v2[0]["replay"]) == ("answered", "analysis_not_cached")


def test_offline_analysis_client_never_answers():
    from RAG.src.utils.errors import LlmUnavailableError
    with pytest.raises(LlmUnavailableError):
        rg.OfflineAnalysisClient().complete_json(None, system="s", user="u")


def test_replay_client_misses_raise():
    with pytest.raises(rg.GenerationNotCached):
        call(rg.ReplayClient({}, "sha"))


def test_diagnose_explains_the_trigger_of_each_rejection_without_network():
    from RAG.src.generation.answer import generate_answer
    from RAG.src.prompts.generation import GENERATION_PROMPT_SHA
    from RAG.tests.test_generation_answer import PROFILE
    questions, v1, res_for, _, replay_client = _replay_setup()
    client = rg.RecordingReplayClient(replay_client._cache, GENERATION_PROMPT_SHA)
    generate = lambda q, r: generate_answer(q, r, client=client, profile=PROFILE, max_tokens=3000)
    diagnostics = rg.diagnose_records(questions, v1, search=res_for, generate=generate, client=client)
    # Q1 rejetée (négation) ; Q2 hors périmètre sans LLM ; Q3 non en cache : ni l'une ni l'autre.
    assert [d["id"] for d in diagnostics] == ["Q1"]
    d = diagnostics[0]
    assert d["reason"] == "significance_not_in_sources" and d["answer_status"] == "unverifiable"
    assert any("n'est pas bénin" in item for item in d["detail"])
    assert d["excerpt"].startswith("Le variant rs80357906") and len(d["excerpt"]) <= 200


def test_atomic_write_flushes_to_disk_before_replacing(tmp_path, monkeypatch):
    """Revue finale n° 2, m5 : os.replace seul protège d'un arrêt du processus, pas d'une coupure
    de courant ; le fichier temporaire est vidé sur disque (fsync) avant le remplacement."""
    import os

    from RAG.experiments import recette_generation as R
    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(R.os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(R.os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[1])
    target = tmp_path / "records.json"
    R._write_json_atomic(target, {"a": "é"})
    assert calls[:2] == ["fsync", "replace"]
    assert target.read_text(encoding="utf-8") == '{"a": "é"}'
    assert not (tmp_path / "records.json.part").exists()
