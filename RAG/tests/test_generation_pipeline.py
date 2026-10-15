from RAG.src.generation.answer import Answer
from RAG.src.generation.pipeline import answer_question
from RAG.tests.test_generation_answer import result


def test_answer_question_times_each_stage_and_never_mutates_the_question():
    ticks = iter([0.0, 1.0, 3.5])
    seen = {}

    def search(q):
        seen["search"] = q
        return result()

    def generate(q, res):
        seen["generate"] = q
        return Answer("answered", "ok", (), "avert.", None, None, "Groq", "m", 0.0, 2500.0, True)

    out = answer_question("  Que sait-on de rs80357906 ?  ", search=search, generate=generate, clock=lambda: next(ticks))

    assert seen == {"search": "  Que sait-on de rs80357906 ?  ", "generate": "  Que sait-on de rs80357906 ?  "}
    assert out.timings_ms["search"] == 1000.0 and out.timings_ms["generation"] == 2500.0
    assert out.timings_ms["total"] == 3500.0


def test_trace_is_only_exposed_on_request():
    out = answer_question("q ?", search=lambda q: result(),
                          generate=lambda q, r: Answer("answered", "ok", (), "a", None, None, "Groq", "m", 0.0, 1.0, True),
                          clock=iter([0.0, 0.1, 0.2]).__next__)
    assert "trace" not in out.as_dict(include_trace=False)
    assert "trace" in out.as_dict(include_trace=True)


def test_history_is_exposed_next_to_the_answer():
    history = ("Historique ClinVar (clinvar:32716) : classé « signification incertaine » jusqu'au 2015-01, "
               "avant la classification actuelle.",)
    out = answer_question("q ?", search=lambda q: result(),
                          generate=lambda q, r: Answer("answered", "ok", (), "a", None, None, "Groq", "m", 0.0, 1.0,
                                                       True, history=history),
                          clock=iter([0.0, 0.1, 0.2]).__next__)
    assert out.as_dict(include_trace=False)["history"] == list(history)


class _FakeSearcher:
    opened, closed, sessions_closed = 0, 0, 0
    fail_enter_on = None
    fail_exit = False

    def __init__(self, **kwargs):
        self.questions = []

    def __enter__(self):
        type(self).opened += 1
        if type(self).fail_enter_on == type(self).opened:
            raise ConnectionError("base injoignable")
        return self

    def __exit__(self, *exc_info):
        type(self).closed += 1
        if type(self).fail_exit:
            raise OSError("fermeture ratée")

    def close(self):
        type(self).sessions_closed += 1

    def search(self, question):
        self.questions.append(question)
        return result()


class _FakeClient:
    closed = 0

    def __init__(self):
        self.calls = []

    def close(self):
        type(self).closed += 1

    def complete_json(self, profile, **kwargs):
        from RAG.src.llm.common import LlmCall
        from RAG.tests.test_generation_answer import ok

        self.calls.append(kwargs)
        return LlmCall(ok(), "gen-1", "Groq", 0.0, 900, 200)


def _wire(monkeypatch, fail_on_client=None):
    import RAG.src.generation.pipeline as pipeline
    from RAG.src.utils.config import GenerationConfig
    from RAG.tests.test_generation_answer import PROFILE

    _FakeSearcher.opened = _FakeSearcher.closed = _FakeSearcher.sessions_closed = _FakeClient.closed = 0
    _FakeSearcher.fail_enter_on, _FakeSearcher.fail_exit = None, False
    built = []

    def build(profile, env, timeout_s):
        built.append(profile)
        if fail_on_client is not None and len(built) == fail_on_client:
            raise RuntimeError("clé absente")
        return _FakeClient()

    monkeypatch.setattr(pipeline, "load_generation_config", lambda path: GenerationConfig(PROFILE, 3000, 60.0))
    monkeypatch.setattr(pipeline, "Searcher", _FakeSearcher)
    monkeypatch.setattr(pipeline, "build_llm_client", build)
    return pipeline


def test_slots_are_handed_out_once_and_closed_on_exit(monkeypatch):
    pipeline = _wire(monkeypatch)
    with pipeline.QuestionPipeline(2) as qp:
        a, b = qp.acquire(), qp.acquire()
        assert a is not None and b is not None and a is not b and qp.acquire() is None
        qp.release(a)
        assert qp.acquire() is a
    assert (_FakeSearcher.opened, _FakeSearcher.closed, _FakeClient.closed) == (2, 2, 2)


def test_a_failed_opening_closes_what_was_already_opened(monkeypatch):
    import pytest

    pipeline = _wire(monkeypatch, fail_on_client=2)
    with pytest.raises(RuntimeError):
        with pipeline.QuestionPipeline(3):
            pass
    assert (_FakeSearcher.opened, _FakeSearcher.closed, _FakeClient.closed) == (2, 2, 1)


def test_a_failed_database_opening_closes_the_http_sessions(monkeypatch):
    import pytest

    pipeline = _wire(monkeypatch)
    _FakeSearcher.fail_enter_on = 2
    with pytest.raises(ConnectionError):
        with pipeline.QuestionPipeline(2):
            pass
    # Emplacement 1 fermé par __exit__ ; le Searcher 2, jamais entré, ferme ses sessions HTTP.
    assert (_FakeSearcher.closed, _FakeSearcher.sessions_closed, _FakeClient.closed) == (1, 1, 1)


def test_a_cleanup_error_does_not_mask_the_opening_error(monkeypatch):
    import pytest

    pipeline = _wire(monkeypatch, fail_on_client=2)
    _FakeSearcher.fail_exit = True
    with pytest.raises(RuntimeError, match="clé absente"):
        with pipeline.QuestionPipeline(2):
            pass


def test_the_analysis_cache_allows_a_single_slot(monkeypatch, tmp_path):
    import pytest

    pipeline = _wire(monkeypatch)
    with pytest.raises(ValueError):
        pipeline.QuestionPipeline(2, analysis_cache_path=tmp_path / "cache.sqlite")
    pipeline.QuestionPipeline(1, analysis_cache_path=tmp_path / "cache.sqlite")


def test_a_slot_cannot_be_released_twice(monkeypatch):
    import pytest

    pipeline = _wire(monkeypatch)
    with pipeline.QuestionPipeline(2) as qp:
        slot = qp.acquire()
        qp.release(slot)
        with pytest.raises(RuntimeError):
            qp.release(slot)
        assert {id(qp.acquire()), id(qp.acquire())} == {id(s) for s in qp._all} and qp.acquire() is None


def test_ask_uses_the_slot_generator_and_the_configured_max_tokens(monkeypatch):
    pipeline = _wire(monkeypatch)
    with pipeline.QuestionPipeline(2) as qp:
        mine, other = qp.acquire(), qp.acquire()
        out = qp.ask(mine, "Que sait-on de rs80357906 ?")

    assert out.answer.status == "answered"
    assert mine.searcher.questions == ["Que sait-on de rs80357906 ?"] and other.searcher.questions == []
    assert [c["max_tokens"] for c in mine.generator.calls] == [3000] and other.generator.calls == []
