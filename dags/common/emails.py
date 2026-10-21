"""Gabarits des e-mails du pipeline, réunis ici pour en reprendre le design en un seul endroit."""
from __future__ import annotations

from html import escape

from dags.common.preflight import Check, Reminder, Status
from dags.common.schedule import ACQUISITION_HOUR

SUBJECT_PREFIX = "[genomique]"

# Gabarits Jinja rendus par SmtpNotifier dans le contexte de la tâche en échec.
FAILURE_SUBJECT = SUBJECT_PREFIX + " Échec {{ ti.dag_id }}.{{ ti.task_id }} ({{ ti.run_id }})"
# Le gabarit par défaut du provider omet l'exception, première chose à lire pour diagnostiquer.
FAILURE_HTML = (
    "<p>Tâche <b>{{ ti.dag_id }}.{{ ti.task_id }}</b> en échec définitif "
    "(essai {{ ti.try_number }}, run {{ ti.run_id }}).</p>"
    "<pre>{{ exception | string | e }}</pre>"
    '<p>Journal : <a href="{{ ti.log_url }}">{{ ti.log_url }}</a></p>'
)

_STATUS_LABEL = {Status.OK: "OK", Status.WARNING: "À surveiller", Status.BLOCKING: "Bloquant"}


def reminder_subject(reminder: Reminder, status: Status) -> str:
    """Sujet lisible dans la liste des mails : échéance, date du run et état global."""
    date = reminder.run_date.strftime("%d/%m/%Y")
    return f"{SUBJECT_PREFIX} {reminder.label} : run du {date} — {_STATUS_LABEL[status]}"


def reminder_html(reminder: Reminder, checks: list[Check], status: Status) -> str:
    """Corps du rappel : quand tourne le run, et ce qu'il faut corriger avant."""
    date = reminder.run_date.strftime("%d/%m/%Y")
    # Pas de « dans une heure » : un rappel rattrapé par Airflow peut partir en retard.
    heure = f"{ACQUISITION_HOUR:02d}:00 UTC"
    if reminder.is_run_day:
        intro = f"Le run mensuel d'acquisition démarre aujourd'hui ({date}) à {heure}."
    elif reminder.days_left == 1:
        intro = f"Le run mensuel d'acquisition démarre demain ({date}) à {heure}."
    else:
        intro = f"Le run mensuel d'acquisition démarre le {date} à {heure}, dans {reminder.days_left} jours."
    rows = "".join(
        f"<tr><td>{escape(c.name)}</td><td><b>{_STATUS_LABEL[c.status]}</b></td>"
        f"<td>{escape(c.detail)}</td></tr>"
        for c in checks
    )
    action = (
        "<p>Rien à faire.</p>"
        if status is Status.OK
        else "<p>Corriger les points ci-dessus avant le run.</p>"
    )
    return f"<p>{escape(intro)}</p><table>{rows}</table>{action}"
