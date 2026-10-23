"""One-time tokens sent by e-mail (verification, password reset).

Only the SHA-256 digest is stored: a database leak must not let anyone verify an account or reset
a password. A plain hash is enough (no salt, no slow hash) because the token is 256 random bits,
not something a user chose.
"""

import hashlib
import secrets


def new_token() -> tuple[str, str]:
    """Return (token for the e-mail link, digest for the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
