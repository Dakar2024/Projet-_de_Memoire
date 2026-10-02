import pytest

from RAG.src.chunking.chunker import check_token_lengths
from RAG.src.utils.errors import DocumentTooLongError


def _counts(texts):
    return [len(text.split()) for text in texts]


def test_documents_within_the_window_pass():
    check_token_lengths(["a", "b"], ["un deux", "trois"], _counts, max_tokens=2)


def test_every_overlong_document_is_named_with_its_length():
    with pytest.raises(DocumentTooLongError) as excinfo:
        check_token_lengths(["ok", "long1", "long2"], ["x", "x x x", "x x x x"], _counts, max_tokens=2)

    message = str(excinfo.value)
    assert "2 document(s)" in message
    assert "long1 (3)" in message and "long2 (4)" in message
    assert "ok" not in message.split(":", 1)[1]


def test_a_count_mismatch_is_a_programming_error():
    with pytest.raises(ValueError):
        check_token_lengths(["a", "b"], ["x"], _counts, max_tokens=5)
