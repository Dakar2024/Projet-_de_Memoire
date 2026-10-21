import json
import logging
import threading
import time

import pytest
from litestar.testing import TestClient

from RAG.src.api.app import create_app
from RAG.src.generation.answer import Answer
from RAG.src.generation.pipeline import PipelineResult
from RAG.src.utils.config import ApiConfig
from RAG.src.utils.errors import (
    IndexEmptyError, LlmPermanentError, LlmQuotaExhaustedError, LlmUnavailableError, QuestionRejectedError,
)
from RAG.tests.test_generation_answer import result

KEY = "k" * 40
H = {"X-API-Key": KEY}
SECRET_QUESTION = "Question confidentielle sur rs80357906 chez ma patiente ?"


class FakePipeline:
    def __init__(self, slots=4, behaviour=None):
        self.free = list(range(slots))
        self.lock = threading.Lock()
        self.behaviour = behaviour or (lambda q: None)
        self.in_use = set()
        self.closed = False
        self.shared = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def acquire(self):
        with self.lock:
            return self.free.pop() if self.free else None

    def release(self, slot):
        with self.lock:
            self.free.append(slot)

    def ask(self, slot, question):
        with self.lock:
            if slot in self.in_use:
                self.shared = True
            self.in_use.add(slot)
        try:
            self.behaviour(question)
            ans = Answer("answered", "Le variant est pathogène.", (), "avert.", None, None, "Groq", "m", 0.0, 1.0, True)
            return PipelineResult(ans, result(), {"analysis": 1.0, "search": 2.0, "generation": 1.0, "total": 4.0})
        finally:
            with self.lock:
                self.in_use.discard(slot)

    def ready(self):
        return {"database": True, "embeddings": True}


class StrictPipeline(FakePipeline):
    """Comme `QuestionPipeline.release` : rendre un emplacement non acquis, ou après la
    fermeture, lève `RuntimeError`."""

    def __init__(self, *a, double_release=False, **kw):
        super().__init__(*a, **kw)
        self.double_release = double_release

    def release(self, slot):
        if self.closed or self.double_release:
            raise RuntimeError("emplacement non acquis ou déjà rendu")
        super().release(slot)


def client(pipeline=None, timeout=120.0, openapi=False):
    pipeline = pipeline or FakePipeline()
    app = create_app(lambda: pipeline, api_config=ApiConfig(4, timeout, 8192, openapi), api_key=KEY)
    return TestClient(app=app), pipeline


def wait_until(condition, limit=5.0):
    deadline = time.monotonic() + limit
    while not condition():
        assert time.monotonic() < deadline, "condition jamais atteinte"
        time.sleep(0.01)


def api_events(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "rag.api"]


def ask(c, question="Que sait-on de rs80357906 ?", headers=H, **extra):
    return c.post("/v1/questions", json={"question": question, **extra}, headers=headers)


def test_health_needs_no_key_and_ready_needs_one():
    c, _ = client()
    with c:
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 401
        assert c.get("/ready", headers=H).json() == {"database": True, "embeddings": True}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "faux"}, {"X-API-Key": KEY[:-1]}])
def test_missing_or_wrong_key_is_401(headers):
    c, _ = client()
    with c:
        r = ask(c, headers=headers)
    assert r.status_code == 401 and r.json()["error"] == "unauthorized" and "request_id" in r.json()


def test_answer_is_200_with_status_sources_disclaimer_and_no_trace_by_default():
    c, _ = client()
    with c:
        r = ask(c)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "answered" and "disclaimer" in body
    assert "trace" not in body and "request_id" in body and body["history"] == []
    with c:
        assert "trace" in ask(c, trace=True).json()


@pytest.mark.parametrize("payload,code", [
    ({"question": ""}, 422), ({"question": "x" * 1001}, 422), ({"question": 3}, 422),
    ({"question": "ok ?", "extra": 1}, 422), ({}, 422),
])
def test_invalid_questions_are_422(payload, code):
    c, _ = client()
    with c:
        assert c.post("/v1/questions", json=payload, headers=H).status_code == code


def test_question_on_an_empty_index_is_503_index_empty():
    def boom(q):
        raise IndexEmptyError("index vide")
    c, _ = client(FakePipeline(behaviour=boom))
    with c:
        assert c.get("/health").status_code == 200
        r = ask(c)
    assert r.status_code == 503 and r.json()["error"] == "index_empty" and "request_id" in r.json()


def test_blank_question_rejected_by_the_pipeline_is_422():
    def boom(q):
        raise QuestionRejectedError("question vide")
    c, _ = client(FakePipeline(behaviour=boom))
    with c:
        assert ask(c, question="   ").status_code == 422


def test_body_too_large_is_413():
    c, _ = client()
    with c:
        r = c.post("/v1/questions", content=b'{"question": "' + b"a" * 9000 + b'"}', headers={**H, "content-type": "application/json"})
    assert r.status_code == 413


def test_malformed_json_is_422():
    c, _ = client()
    with c:
        r = c.post("/v1/questions", content=b"{not json", headers={**H, "content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_question"


def test_wrong_method_is_405_with_the_standard_error_body():
    c, _ = client()
    with c:
        r = c.get("/v1/questions", headers=H)
    assert r.status_code == 405 and set(r.json()) == {"error", "message", "request_id"}


@pytest.mark.parametrize("error,code", [
    (LlmUnavailableError("503"), 503), (LlmQuotaExhaustedError("quota", retry_after_s=42.0), 503),
    (LlmPermanentError("402"), 500), (RuntimeError("bug"), 500),
])
def test_errors_map_to_http_codes_without_internal_detail(error, code):
    def boom(q):
        raise error
    c, _ = client(FakePipeline(behaviour=boom))
    with c:
        r = ask(c)
    assert r.status_code == code and set(r.json()) == {"error", "message", "request_id"}
    assert "Traceback" not in r.text and "bug" not in r.text
    if isinstance(error, LlmQuotaExhaustedError):
        assert r.headers["retry-after"] == "42"


def test_slots_are_never_shared_between_concurrent_questions():
    gate = threading.Event()
    pipeline = FakePipeline(slots=4, behaviour=lambda q: gate.wait(5))
    c, _ = client(pipeline)
    codes = []
    with c:
        threads = [threading.Thread(target=lambda: codes.append(ask(c).status_code)) for _ in range(6)]
        for t in threads:
            t.start()
        wait_until(lambda: len(pipeline.in_use) == 4)
        # On attend les deux refus avant d'ouvrir la porte : sinon un créneau libéré
        # pourrait servir une requête tardive en 200 au lieu de 429.
        wait_until(lambda: len(codes) == 2 and set(codes) == {429})
        gate.set()
        for t in threads:
            t.join()
    assert sorted(codes) == [200, 200, 200, 200, 429, 429]
    assert pipeline.shared is False


def test_deadline_returns_503_and_keeps_the_slot_busy(caplog):
    caplog.set_level(logging.INFO)
    release = threading.Event()
    pipeline = FakePipeline(slots=1, behaviour=lambda q: release.wait(5))
    c, _ = client(pipeline, timeout=0.3)
    with c:
        first = ask(c)
        second = ask(c)
        release.set()
        wait_until(lambda: pipeline.free)
        third = ask(c)
    assert first.status_code == 503 and first.json()["error"] == "timeout"
    assert second.status_code == 429
    assert third.status_code == 200
    assert any(e.get("event") == "error" and e.get("error") == "timeout" for e in api_events(caplog))


def test_question_text_never_logged_even_on_errors(caplog, capfd):
    def boom(q):
        raise LlmUnavailableError("indisponible")
    caplog.set_level(logging.DEBUG)
    for pipeline in (FakePipeline(), FakePipeline(behaviour=boom)):
        c, _ = client(pipeline)
        with c:
            ask(c, question=SECRET_QUESTION)
            ask(c, question=SECRET_QUESTION, headers={"X-API-Key": "faux"})
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "confidentielle" not in joined and KEY not in joined
    out, err = capfd.readouterr()
    assert "confidentielle" not in out + err and KEY not in out + err
    assert any(json.loads(r.getMessage()).get("event") == "question" for r in caplog.records if r.name == "rag.api")


def test_release_after_shutdown_is_logged_without_text(caplog):
    caplog.set_level(logging.INFO)
    gate = threading.Event()
    pipeline = StrictPipeline(slots=1, behaviour=lambda q: gate.wait(5))
    c, _ = client(pipeline, timeout=0.3)
    with c:
        r = ask(c, question=SECRET_QUESTION)
    assert r.status_code == 503 and pipeline.closed
    gate.set()
    wait_until(lambda: any(e.get("event") == "release_after_shutdown" for e in api_events(caplog)))
    assert any(e.get("event") == "shutdown_threads_active" for e in api_events(caplog))
    assert all("confidentielle" not in json.dumps(e) for e in api_events(caplog))


def test_shutdown_waits_for_an_active_thread_before_closing_the_pipeline(caplog):
    """Revue finale n° 2, m3 : fermer les connexions sous un fil encore actif (dans libpq) est
    dangereux. L'arrêt attend les fils (borné par request_timeout_s) AVANT de fermer : un fil qui
    se termine pendant cette attente rend son emplacement à un pipeline encore ouvert."""
    caplog.set_level(logging.INFO)
    gate = threading.Event()
    pipeline = StrictPipeline(slots=1, behaviour=lambda q: gate.wait(5))
    c, _ = client(pipeline, timeout=0.5)
    with c:
        assert ask(c).status_code == 503
        threading.Timer(0.05, gate.set).start()
    assert pipeline.closed and pipeline.free == [0]
    assert not any(e.get("event") == "release_after_shutdown" for e in api_events(caplog))


def test_double_release_on_an_open_pipeline_is_not_swallowed(caplog):
    caplog.set_level(logging.INFO)
    c, _ = client(StrictPipeline(double_release=True))
    with c:
        r = ask(c)
    assert r.status_code == 500 and r.json()["error"] == "internal"
    assert not any(e.get("event") == "release_after_shutdown" for e in api_events(caplog))
    assert any(e.get("exception") == "RuntimeError" for e in api_events(caplog))


def test_late_error_after_deadline_is_logged_without_text(caplog):
    caplog.set_level(logging.INFO)
    gate = threading.Event()

    def late(q):
        gate.wait(5)
        raise LlmUnavailableError(f"échec tardif : {q}")
    c, _ = client(FakePipeline(slots=1, behaviour=late), timeout=0.3)
    with c:
        assert ask(c, question=SECRET_QUESTION).status_code == 503
        gate.set()
        wait_until(lambda: any(e.get("event") == "late_error" for e in api_events(caplog)))
    late_events = [e for e in api_events(caplog) if e.get("event") == "late_error"]
    assert late_events[0]["exception"] == "LlmUnavailableError"
    assert "confidentielle" not in "\n".join(r.getMessage() for r in caplog.records)


def test_pipeline_is_closed_on_shutdown():
    c, pipeline = client()
    with c:
        pass
    assert pipeline.closed


def test_openapi_is_disabled():
    c, _ = client()
    with c:
        assert c.get("/schema").status_code == 404


def test_openapi_can_be_enabled_by_config():
    c, _ = client(openapi=True)
    with c:
        assert c.get("/schema/openapi.json").status_code == 200


# --- vague finale ---

@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded",
                                          "application/jsonx"])
def test_a_body_that_is_not_declared_json_is_refused(content_type):
    c, pipeline = client()
    headers = {**H, **({"content-type": content_type} if content_type else {})}
    with c:
        r = c.post("/v1/questions", content=b'{"question": "Que sait-on de rs80357906 ?"}', headers=headers)
    assert r.status_code == 415 and r.json()["error"] == "unsupported_media_type"
    assert set(r.json()) == {"error", "message", "request_id"}


def test_json_with_a_charset_is_accepted_and_the_key_is_checked_first():
    c, _ = client()
    with c:
        r = c.post("/v1/questions", content=b'{"question": "Que sait-on de rs80357906 ?"}',
                   headers={**H, "content-type": "application/json; charset=utf-8"})
        assert r.status_code == 200
        r = c.post("/v1/questions", content=b"x", headers={"content-type": "text/plain"})
        assert r.status_code == 401


def test_late_result_after_deadline_is_logged_with_status_and_cost_only(caplog):
    caplog.set_level(logging.INFO)
    gate = threading.Event()
    c, _ = client(FakePipeline(slots=1, behaviour=lambda q: gate.wait(5)), timeout=0.3)
    with c:
        assert ask(c, question=SECRET_QUESTION).status_code == 503
        gate.set()
        wait_until(lambda: any(e.get("event") == "late_result" for e in api_events(caplog)))
    event = next(e for e in api_events(caplog) if e.get("event") == "late_result")
    assert event["status"] == "answered" and event["cost_usd"] == 0.0 and "request_id" in event
    assert "confidentielle" not in "\n".join(r.getMessage() for r in caplog.records)
