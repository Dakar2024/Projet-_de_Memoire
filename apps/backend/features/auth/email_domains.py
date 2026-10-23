"""Who may request an account, decided from the e-mail domain alone."""

# Consumer mailbox providers: access is for professionals, identified by their institution's
# address. Same list as apps/frontend/src/features/auth/email.ts (test_email_domains checks it).
CONSUMER_DOMAINS = frozenset({
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.fr", "ymail.com",
    "hotmail.com", "hotmail.fr", "outlook.com", "outlook.fr", "live.com", "live.fr", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com",
    "proton.me", "protonmail.com",
    "gmx.com", "gmx.fr", "gmx.de",
    "yandex.com", "yandex.ru", "mail.ru", "mail.com",
    "zoho.com",
    "orange.fr", "wanadoo.fr", "free.fr", "sfr.fr", "neuf.fr", "laposte.net", "bbox.fr",
})


def normalize_email(email: str) -> str:
    return email.strip().lower()


def domain_of(email: str) -> str:
    return normalize_email(email).rpartition("@")[2]


def is_professional_email(email: str) -> bool:
    domain = domain_of(email)
    return bool(domain) and domain not in CONSUMER_DOMAINS


def is_allowed_domain(email: str, allowed_domains: list[str]) -> bool:
    """True when the domain is listed, or is a subdomain of a listed one (chu.aphp.fr ⊂ aphp.fr)."""
    domain = domain_of(email)
    return any(domain == d or domain.endswith(f".{d}") for d in (a.strip().lower() for a in allowed_domains) if d)
