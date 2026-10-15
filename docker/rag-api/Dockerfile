# Image du RAG (API et outils de mesure) : dépendances seules, vérifiées par empreinte, code monté en lecture seule.
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016 AS production

# Roues seulement : les dépendances de construction d'un sdist échapperaient à la vérification.
COPY docker/rag-api/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.lock

# Étape des tests d'intégration : la même image, plus pytest.
FROM production AS test
COPY docker/rag-api/requirements-test.lock /tmp/requirements-test.lock
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements-test.lock
