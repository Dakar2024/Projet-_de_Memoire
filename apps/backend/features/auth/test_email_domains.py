import re
from pathlib import Path

import pytest

from features.auth.email_domains import (
    CONSUMER_DOMAINS,
    domain_of,
    is_allowed_domain,
    is_professional_email,
    normalize_email,
)

FRONTEND_LIST = Path(__file__).parents[3] / "frontend" / "src" / "features" / "auth" / "email.ts"


@pytest.mark.parametrize("email", ["a@gmail.com", "A@GMAIL.COM", " b@orange.fr ", "c@proton.me"])
def test_consumer_mailboxes_are_refused(email: str):
    assert not is_professional_email(email)


@pytest.mark.parametrize("email", ["a@aphp.fr", "b@inserm.fr", "c@chu-dakar.sn"])
def test_institution_mailboxes_are_accepted(email: str):
    assert is_professional_email(email)


def test_normalization():
    assert normalize_email("  Jane.Doe@APHP.fr ") == "jane.doe@aphp.fr"
    assert domain_of("Jane@Sub.Example.ORG") == "sub.example.org"


@pytest.mark.parametrize(
    ("email", "allowed", "expected"),
    [
        ("a@aphp.fr", ["aphp.fr"], True),
        ("a@chu.aphp.fr", ["aphp.fr"], True),
        ("a@notaphp.fr", ["aphp.fr"], False),
        ("a@aphp.fr", [" APHP.FR "], True),
        ("a@aphp.fr", [], False),
        ("a@aphp.fr", [""], False),
    ],
)
def test_allowed_domains(email: str, allowed: list[str], expected: bool):
    assert is_allowed_domain(email, allowed) is expected


@pytest.mark.skipif(not FRONTEND_LIST.exists(), reason="frontend absent")
def test_same_list_as_the_frontend():
    source = FRONTEND_LIST.read_text(encoding="utf-8")
    block = source[source.index("CONSUMER_DOMAINS") : source.index("])")]
    assert set(re.findall(r"'([^']+)'", block)) == CONSUMER_DOMAINS
