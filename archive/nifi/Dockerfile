# Étend l'image officielle NiFi pour pouvoir exécuter scripts/run_collection.py
# via ExecuteStreamCommand, sans réimplémenter la logique de collecte en NiFi natif
# (voir archive/nifi/README.md pour la justification de ce choix).
FROM apache/nifi:2.6.0

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# venv dédié : on ne touche pas à l'interpréteur système utilisé par les
# fonctionnalités Python natives de NiFi (nifi.python.command).
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/collecte-venv \
    && /opt/collecte-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && chown -R nifi:nifi /opt/collecte-venv

USER nifi
