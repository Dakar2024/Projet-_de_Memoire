import os
import tempfile

import pytest

# Airflow crée son répertoire de travail (airflow.cfg, logs) dès l'import. Les tests
# utilisent toujours un dossier temporaire neuf, y compris quand AIRFLOW_HOME est déjà
# exporté dans le shell : sinon ils écriraient dans l'installation Airflow réelle du
# développeur. conftest.py est chargé avant les modules de test, donc avant tout
# import d'Airflow.
os.environ["AIRFLOW_HOME"] = tempfile.mkdtemp(prefix="airflow-tests-")

# Destinataire d'alerte factice : les DAGs le lisent dans l'environnement au moment
# de leur construction, et les tests vérifient qu'il arrive bien jusqu'à eux.
os.environ["ALERT_EMAIL"] = "alerte@example.test"


@pytest.fixture
def smtp_outbox(monkeypatch):
    """Remplace le hook SMTP : capture les mails au lieu de les envoyer."""
    import airflow.providers.smtp.hooks.smtp as smtp_module

    mails = []

    class FakeSmtpHook:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send_email_smtp(self, **kwargs):
            mails.append(kwargs)

    monkeypatch.setattr(smtp_module, "SmtpHook", FakeSmtpHook)
    return mails
