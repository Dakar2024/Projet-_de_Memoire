import pytest
import responses

from ingestion.http_client import NcbiClient, RateLimiter


def test_rate_limiter_does_not_sleep_on_first_call():
    slept = []
    limiter = RateLimiter(0.11, sleep_fn=slept.append, time_fn=lambda: 0.0)
    limiter.wait()
    assert slept == []


def test_rate_limiter_sleeps_remaining_interval_on_second_call():
    clock = {"t": 0.0}

    def fake_time():
        return clock["t"]

    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    limiter = RateLimiter(0.11, sleep_fn=fake_sleep, time_fn=fake_time)
    limiter.wait()
    clock["t"] += 0.02
    limiter.wait()

    assert slept == [pytest.approx(0.09)]


def test_rate_limiter_does_not_sleep_if_interval_already_elapsed():
    clock = {"t": 0.0}
    slept = []
    limiter = RateLimiter(
        0.11, sleep_fn=slept.append, time_fn=lambda: clock["t"]
    )
    limiter.wait()
    clock["t"] += 0.5
    limiter.wait()
    assert slept == []


def _no_wait_limiter():
    return RateLimiter(0.0, sleep_fn=lambda s: None)


@responses.activate
def test_esearch_returns_idlist():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["3043"]}},
        status=200,
    )
    client = NcbiClient(email="test@example.com", rate_limiter=_no_wait_limiter())
    assert client.esearch(db="gene", term="HBB[gene]") == ["3043"]


@responses.activate
def test_esearch_sends_email_and_api_key_params():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": []}},
        status=200,
    )
    client = NcbiClient(
        email="test@example.com", api_key="secret", rate_limiter=_no_wait_limiter()
    )
    client.esearch(db="gene", term="HBB[gene]")
    sent_params = responses.calls[0].request.params
    assert sent_params["email"] == "test@example.com"
    assert sent_params["api_key"] == "secret"
    # NCBI attend `tool` en plus de `email` pour identifier l'appelant.
    assert sent_params["tool"] == "rag-genomique-ingestion"


@responses.activate
def test_esearch_retries_transient_errors_then_succeeds():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        json={"esearchresult": {"idlist": ["3043"]}},
        status=200,
    )
    # Session réelle (avec l'adaptateur de retry) et non un limiter injecté seulement :
    # on veut vérifier que le 503 est réessayé de façon transparente.
    client = NcbiClient(email="test@example.com", rate_limiter=_no_wait_limiter())

    assert client.esearch(db="gene", term="HBB[gene]") == ["3043"]
    assert len(responses.calls) == 2


@responses.activate
def test_esummary_returns_result_for_uid():
    responses.add(
        responses.GET,
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        json={"result": {"3043": {"name": "HBB"}}},
        status=200,
    )
    client = NcbiClient(email="test@example.com", rate_limiter=_no_wait_limiter())
    assert client.esummary(db="gene", uid="3043") == {"name": "HBB"}
