# Recherche du RAG (E2a), future API (E2b). Image minimale : le code est monté en
# lecture seule, seules les dépendances sont installées. Versions épinglées, les mêmes
# que celles du pipeline et de l'image Airflow.
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

COPY requirements.txt /tmp/requirements.txt
COPY RAG/requirements.txt /tmp/rag-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/rag-requirements.txt
