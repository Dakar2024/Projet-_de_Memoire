import os

# Required settings, so modules that read `core.settings` import without a .env file.
# Unit tests never reach PostgreSQL or Redis; integration tests will bring their own.
for key, value in {
    "PICCOLO_CONF": "core.database",  # where Piccolo finds its engine (set by the Makefile and Dockerfile too)
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_DB": "test",
    "SECRET_KEY": "test-secret-key-of-at-least-32-bytes",
    "ADMIN_EMAIL": "admin@example.org",
    "ADMIN_PASSWORD": "test",
}.items():
    os.environ.setdefault(key, value)
