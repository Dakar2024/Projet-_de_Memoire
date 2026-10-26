"""Contenu des e-mails du pipeline, rendus avec le design de ceux de l'application. Pur : l'envoi
passe par `dags.common.mailer`."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from dags.common.preflight import Check, Reminder, Status
from dags.common.schedule import ACQUISITION_HOUR

APP_NAME = "Genomica"
SUBJECT_PREFIX = "[genomique]"
# Image intégrée au message (cid:), comme dans les e-mails de l'application : pas de serveur public,
# et Gmail bloque les images en data:.
LOGO_CID = "genomica-logo"

_jinja = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)

_STATUS_LABEL = {Status.OK: "OK", Status.WARNING: "À surveiller", Status.BLOCKING: "Bloquant"}
_STATUS_COLOR = {Status.OK: "#0f766e", Status.WARNING: "#b45309", Status.BLOCKING: "#b91c1c"}
_REMINDER_TITLE = {
    Status.OK: "Tout est prêt pour le run mensuel",
    Status.WARNING: "Un point à surveiller avant le run mensuel",
    Status.BLOCKING: "Un point bloque le run mensuel",
}


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class _Row:
    label: str
    status: str
    detail: str
    color: str


@dataclass(frozen=True)
class Failure:
    """Ce qu'un e-mail d'échec doit dire, extrait du contexte Airflow par `dags.common.alerting`."""

    dag_id: str
    dag_description: str | None
    task_id: str
    run_id: str
    try_number: int
    # Vrai pour une `AirflowFailException` : la tâche a renoncé aux relances.
    definitive: bool
    error: str
    log_url: str | None


@dataclass(frozen=True)
class RunSuccess:
    """Ce qu'un e-mail de succès doit dire, réuni par la dernière tâche d'un DAG de panel."""

    dag_id: str
    dag_description: str | None
    run_id: str
    month: str
    started: dt.datetime
    ended: dt.datetime
    # Nombre de Clear du run : au-dessus de zéro, c'est une relance après échec qui a abouti.
    clear_number: int
    # Bilan de `index_rag_documents` (XCom), absent si la tâche n'en a pas rendu.
    index: dict | None
    longest: list[tuple[str, float]]
    run_url: str | None


def _compose(
    subject: str,
    title: str,
    paragraphs: list[str],
    *,
    rows: list[_Row] | None = None,
    code: str | None = None,
    button_url: str | None = None,
    button_label: str | None = None,
    footnote: str | None = None,
) -> Email:
    """Rend un e-mail en HTML (gabarit commun) et en texte brut, avec le même contenu."""
    lines = [title, "", *paragraphs]
    if rows:
        lines += ["", *(f"- {row.label} : {row.status} — {row.detail}" for row in rows)]
    if code:
        lines += ["", code]
    if button_url:
        lines += ["", f"{button_label} : {button_url}"]
    if footnote:
        lines += ["", footnote]
    html = _jinja.get_template("message.html").render(
        app_name=APP_NAME,
        logo_cid=LOGO_CID,
        year=dt.datetime.now(dt.UTC).year,
        title=title,
        paragraphs=paragraphs,
        rows=rows,
        code=code,
        button_url=button_url,
        button_label=button_label,
        footnote=footnote,
    )
    return Email(subject=f"{SUBJECT_PREFIX} {subject}", text="\n".join(lines), html=html)


def reminder_email(reminder: Reminder, checks: list[Check], status: Status) -> Email:
    """Rappel à J-2 ou le jour J : quand tourne le run, et ce qu'il faut corriger avant."""
    date = reminder.run_date.strftime("%d/%m/%Y")
    # Pas de « dans une heure » : un rappel rattrapé par Airflow peut partir en retard.
    heure = f"{ACQUISITION_HOUR:02d}:00 UTC"
    if reminder.is_run_day:
        intro = f"Le run mensuel d'acquisition démarre aujourd'hui ({date}) à {heure}."
    elif reminder.days_left == 1:
        intro = f"Le run mensuel d'acquisition démarre demain ({date}) à {heure}."
    else:
        intro = f"Le run mensuel d'acquisition démarre le {date} à {heure}, dans {reminder.days_left} jours."
    action = "Rien à faire." if status is Status.OK else "Corriger les points ci-dessous avant le run."
    rows = [
        _Row(check.name, _STATUS_LABEL[check.status], check.detail, _STATUS_COLOR[check.status])
        for check in checks
    ]
    return _compose(
        f"{reminder.label} : run du {date} — {_STATUS_LABEL[status]}",
        _REMINDER_TITLE[status],
        [intro, action],
        rows=rows,
        footnote="Rappel envoyé à J-2 et le jour J, avec les contrôles faits au moment de l'envoi.",
    )


def catch_up_email(scheduled: dt.datetime, started: dt.datetime, month: str) -> Email:
    """Rattrapage : l'échéance manquée, le départ réel et le mois traité."""
    processed = f"{month[5:7]}/{month[:4]}"
    missed = f"{scheduled:%m/%Y}"
    paragraphs = [
        (
            f"Le run mensuel d'acquisition prévu le {scheduled:%d/%m/%Y à %H:%M} UTC n'a pas pu "
            "partir à l'heure : la machine ou la pile était arrêtée."
        ),
        (
            f"Airflow l'a rattrapé automatiquement : il a démarré le {started:%d/%m/%Y à %H:%M} UTC. "
            f"Mois traité : {processed}."
        ),
    ]
    # Seul le mois en cours est ingéré : un départ le mois suivant abandonne celui de l'échéance.
    if missed != processed:
        paragraphs.append(
            f"Le mois {missed} n'est pas rattrapé : le pipeline ne traite que le mois en cours."
        )
    paragraphs.append("Rien à faire.")
    return _compose(
        f"Rattrapage : run du {scheduled:%d/%m/%Y} lancé en retard",
        "Run mensuel rattrapé",
        paragraphs,
        footnote="Un e-mail suivra si une tâche échoue.",
    )


def _duration(seconds: float) -> str:
    """Durée lisible : `4 min 20 s`, `8 s`."""
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes} min {secs:02d} s" if minutes else f"{secs} s"


def _thousands(number: int) -> str:
    return f"{number:,}".replace(",", " ")


def success_email(success: RunSuccess) -> Email:
    """Succès d'un run de panel : mois traité, durée, relance éventuelle, index RAG et tâches longues."""
    month = f"{success.month[5:7]}/{success.month[:4]}"
    relaunched = success.clear_number > 0
    where = success.dag_description or success.dag_id
    paragraphs = [
        f"{where} ({success.dag_id}), run {success.run_id}.",
        (
            f"Mois traité : {month}. Démarré le {success.started:%d/%m/%Y à %H:%M} UTC, "
            f"durée {_duration((success.ended - success.started).total_seconds())}."
        ),
    ]
    if relaunched:
        paragraphs.append("Le run avait échoué : la relance est allée jusqu'au bout.")
    if success.index:
        paragraphs.append(
            f"Index RAG : {_thousands(success.index['embedded'])} vectorisés, "
            f"{_thousands(success.index['deleted'])} supprimés, "
            f"{_thousands(success.index['unchanged'])} inchangés."
        )
    rows = [
        _Row(task_id, "OK", _duration(seconds), _STATUS_COLOR[Status.OK])
        for task_id, seconds in success.longest
    ]
    suffix = " après relance" if relaunched else ""
    return _compose(
        f"Succès {success.dag_id} — {month}{suffix}",
        f"Run du panel terminé{suffix}",
        paragraphs,
        rows=rows,
        button_url=success.run_url,
        button_label="Ouvrir le run",
        footnote="Tâches les plus longues ci-dessus. Un e-mail de succès part à chaque run de panel réussi.",
    )


def failure_email(failure: Failure) -> Email:
    """Échec définitif d'une tâche : ce qui a échoué, le type d'échec, l'erreur et le journal."""
    where = failure.dag_description or failure.dag_id
    if failure.definitive:
        kind = (
            "Échec définitif, sans relance : réessayer referait la même erreur (configuration, "
            "données ou mois refusé). Corriger la cause avant de relancer."
        )
    else:
        essais = f"{failure.try_number} essai{'s' if failure.try_number > 1 else ''}"
        kind = (
            f"Échec après {essais} : l'erreur peut être passagère (source ou réseau indisponible). "
            "Relancer plus tard suffit souvent ; sinon, lire le journal."
        )
    return _compose(
        f"Échec {failure.dag_id}.{failure.task_id}",
        f"La tâche {failure.task_id} a échoué",
        [f"{where} ({failure.dag_id}), run {failure.run_id}.", kind, "Message d'erreur :"],
        code=failure.error,
        button_url=failure.log_url,
        button_label="Ouvrir le journal",
        footnote="Marche à suivre : reference/procedure_reprise.md, § 3 « Un e-mail d'échec ».",
    )
