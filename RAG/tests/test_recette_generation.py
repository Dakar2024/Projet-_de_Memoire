import json
from types import SimpleNamespace

import pytest

from RAG.experiments import recette_generation as rg
from RAG.experiments.recette_generation import CachedGenerator, score_recette, summarize
from RAG.src.llm.common import LlmCall


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
