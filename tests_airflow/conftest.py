import os
import tempfile

# Airflow crée son répertoire de travail (airflow.cfg, logs) dès l'import. Les tests
# utilisent toujours un dossier temporaire neuf, y compris quand AIRFLOW_HOME est déjà
# exporté dans le shell : sinon ils écriraient dans l'installation Airflow réelle du
# développeur. conftest.py est chargé avant les modules de test, donc avant tout
# import d'Airflow.
os.environ["AIRFLOW_HOME"] = tempfile.mkdtemp(prefix="airflow-tests-")
