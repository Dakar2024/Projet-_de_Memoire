import os
import tempfile

# Airflow crée son répertoire de travail (airflow.cfg, logs) dès l'import. Sans
# cette ligne, les tests écriraient dans ~/airflow sur la machine du développeur.
# conftest.py est chargé avant les modules de test, donc avant tout import d'Airflow.
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-tests-"))
