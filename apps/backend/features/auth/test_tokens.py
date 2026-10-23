from features.auth.tokens import hash_token, new_token


def test_digest_is_stored_not_token():
    token, digest = new_token()
    assert token != digest
    assert digest == hash_token(token)
    assert len(digest) == 64


def test_tokens_are_unique():
    assert len({new_token()[0] for _ in range(100)}) == 100
