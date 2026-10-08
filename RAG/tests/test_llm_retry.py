import pytest
import requests

from RAG.src.llm.common import post_with_bounded_retry


def _response(status, retry_after=None):
    r = requests.Response()
    r.status_code = status
    if retry_after is not None:
        r.headers["Retry-After"] = retry_after
    return r


def test_received_503_is_retried_then_succeeds():
    replies = iter([_response(503), _response(200)])
    waits = []

    result = post_with_bounded_retry(lambda: next(replies), sleep=waits.append)

    assert result.status_code == 200 and waits == [1.0]


def test_retry_after_is_respected_and_capped():
    replies = iter([_response(429, "7"), _response(429, "999"), _response(200)])
    waits = []

    post_with_bounded_retry(lambda: next(replies), sleep=waits.append)

    assert waits == [7.0, 30.0]


def test_at_most_two_retries_then_the_last_response_is_returned():
    calls = []

    def send():
        calls.append(1)
        return _response(502)

    assert post_with_bounded_retry(send, sleep=lambda s: None).status_code == 502
    assert len(calls) == 3


@pytest.mark.parametrize("status", [200, 400, 401, 402, 500, 504])
def test_other_statuses_are_never_retried(status):
    calls = []

    def send():
        calls.append(1)
        return _response(status)

    post_with_bounded_retry(send, sleep=lambda s: None)
    assert len(calls) == 1


def test_network_errors_are_never_retried():
    calls = []

    def send():
        calls.append(1)
        raise requests.ConnectionError("coupé")

    with pytest.raises(requests.ConnectionError):
        post_with_bounded_retry(send, sleep=lambda s: None)
    assert len(calls) == 1


def test_restricted_statuses_leave_429_to_the_caller():
    calls = []

    def send():
        calls.append(1)
        return _response(429)

    post_with_bounded_retry(send, sleep=lambda s: None, statuses=(502, 503))
    assert len(calls) == 1
