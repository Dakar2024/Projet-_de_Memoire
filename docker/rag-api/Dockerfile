# Image du RAG : API (E2b) et outil de mesure (E2a). Le code est monté en lecture seule ;
# seules les dépendances sont installées, toutes vérifiées par empreinte.
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

COPY docker/rag-api/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
