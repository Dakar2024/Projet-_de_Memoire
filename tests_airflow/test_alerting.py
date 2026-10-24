import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from airflow.sdk.exceptions import AirflowFailException

from dags.common.alerting import alert_args, alert_recipients

ROOT = Path(__file__).resolve().parents[1]


def test_recipients_are_split_on_commas_and_trimmed(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", " a@example.test, ,b@example.test ")

    assert alert_recipients() == ["a@example.test", "b@example.test"]


def test_no_recipient_means_no_callback(monkeypatch):
    """Sans destinataire, aucune tentative d'envoi : un .env vide ne casse rien."""
    monkeypatch.setenv("ALERT_EMAIL", "")

    assert alert_args() == {}


def _failure_context(exception, try_number=1):
    ti = SimpleNamespace(
        dag_id="dag_genomic_pipeline_brca", task_id="bronze_to_silver",
        run_id="manual__2026-10-24", try_number=try_number, log_url="http://localhost:8080/log",
    )
    return {"ti": ti, "dag": SimpleNamespace(description="Pipeline médaillon — BRCA"),
            "exception": exception}


def test_failure_callback_sends_the_failure_email_to_the_recipients(monkeypatch, smtp_outbox):
    monkeypatch.setenv("ALERT_EMAIL", "a@example.test")
    notifier = alert_args()["on_failure_callback"]

    notifier.notify(_failure_context(AirflowFailException("mois refusé")))

    assert smtp_outbox[0]["to"] == ["a@example.test"]
    assert smtp_outbox[0]["subject"] == "[genomique] Échec dag_genomic_pipeline_brca.bronze_to_silver"
    email = smtp_outbox[0]["email"]
    assert "mois refusé" in email.text
    assert "Pipeline médaillon — BRCA" in email.text
    assert "http://localhost:8080/log" in email.text


def test_an_airflow_fail_exception_is_reported_as_definitive(monkeypatch, smtp_outbox):
    monkeypatch.setenv("ALERT_EMAIL", "a@example.test")

    alert_args()["on_failure_callback"].notify(_failure_context(AirflowFailException("x")))

    assert "sans relance" in smtp_outbox[0]["email"].text


def test_any_other_exception_is_reported_after_its_retries(monkeypatch, smtp_outbox):
    monkeypatch.setenv("ALERT_EMAIL", "a@example.test")

    alert_args()["on_failure_callback"].notify(_failure_context(ConnectionError("x"), try_number=4))

    assert "après 4 essais" in smtp_outbox[0]["email"].text


def test_a_failure_without_exception_still_sends_an_email(monkeypatch, smtp_outbox):
    """Une tâche tuée (délai dépassé, zombie) peut échouer sans exception dans le contexte."""
    monkeypatch.setenv("ALERT_EMAIL", "a@example.test")

    alert_args()["on_failure_callback"].notify(_failure_context(None))

    assert "aucun message" in smtp_outbox[0]["email"].text


def test_the_mailer_still_finds_the_smtp_client_of_the_provider():
    """`send_email` passe par le client SMTP interne du hook (SmtpHook n'envoie que son propre MIME,
    logo en pièce jointe ordinaire) : une montée de version du provider qui le renomme doit casser ici."""
    from airflow.providers.smtp.hooks.smtp import SmtpHook

    assert hasattr(SmtpHook(), "_smtp_client")


def test_send_email_uses_the_smtp_connection_and_its_sender(monkeypatch):
    import airflow.providers.smtp.hooks.smtp as smtp_module

    from dags.common import mailer
    from dags.common.emails import Email

    sent = []

    class FakeHook:
        from_email = "alertes@example.test"
        _smtp_client = SimpleNamespace(send_message=sent.append)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(smtp_module, "SmtpHook", FakeHook)

    mailer.send_email(["a@example.test"], Email(subject="s", text="t", html="<p>h</p>"))

    assert sent[0]["From"] == "Genomica <alertes@example.test>"
    assert sent[0]["To"] == "a@example.test"


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
