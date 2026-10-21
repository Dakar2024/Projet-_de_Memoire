import re
from pathlib import Path

import pytest
import yaml

from dags.common.alerting import alert_args, alert_recipients

ROOT = Path(__file__).resolve().parents[1]


def test_recipients_are_split_on_commas_and_trimmed(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", " a@example.test, ,b@example.test ")

    assert alert_recipients() == ["a@example.test", "b@example.test"]


def test_no_recipient_means_no_callback(monkeypatch):
    """Sans destinataire, aucune tentative d'envoi : un .env vide ne casse rien."""
    monkeypatch.setenv("ALERT_EMAIL", "")

    assert alert_args() == {}


def test_failure_callback_targets_the_recipients_and_names_the_task(monkeypatch):
    from airflow.providers.smtp.notifications.smtp import SmtpNotifier

    monkeypatch.setenv("ALERT_EMAIL", "a@example.test")
    notifier = alert_args()["on_failure_callback"]

    assert isinstance(notifier, SmtpNotifier)
    assert notifier.to == ["a@example.test"]
    assert "ti.task_id" in notifier.subject
    assert "exception" in notifier.html_content


@pytest.fixture
def compose_smtp_connection(monkeypatch):
    """Charge la connection `smtp_default` telle que docker compose l'injecte, valeurs interpolées."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    raw = compose["x-airflow-common"]["environment"]["AIRFLOW_CONN_SMTP_DEFAULT"]
    values = {"RESEND_API_KEY": "re_test", "ALERT_FROM": "alertes@example.test"}
    interpolated = re.sub(r"\$\{(\w+):-\}", lambda m: values[m.group(1)], raw)
    monkeypatch.setenv("AIRFLOW_CONN_SMTP_DEFAULT", interpolated)

    from airflow.providers.smtp.hooks.smtp import SmtpHook

    hook = SmtpHook()
    hook.smtp_connection = hook.get_connection("smtp_default")
    return hook


def test_compose_connection_uses_resend_over_implicit_ssl(compose_smtp_connection):
    """Port 465 : SSL implicite, et surtout pas de STARTTLS par-dessus (refusé par le serveur)."""
    hook = compose_smtp_connection

    assert (hook.host, hook.port, hook.smtp_user) == ("smtp.resend.com", 465, "resend")
    assert hook.use_ssl is True
    assert hook.smtp_starttls is False
    assert hook.smtp_password == "re_test"
    assert hook.from_email == "alertes@example.test"


def test_alert_check_dag_is_manual_paused_and_never_retried():
    """Le DAG de vérification ne doit jamais tourner seul ni noyer la boîte aux relances."""
    from dags.dag_test_alerte import dag

    assert dag.schedule is None
    assert dag.is_paused_upon_creation is True
    assert dag.get_task("echec_volontaire").retries == 0
    assert "on_failure_callback" in dag.default_args
