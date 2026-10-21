import datetime as dt

from dags.common.emails import reminder_html, reminder_subject
from dags.common.preflight import Check, Reminder, Status

EARLY = Reminder(run_date=dt.date(2026, 11, 10), days_left=2)
RUN_DAY = Reminder(run_date=dt.date(2026, 11, 10), days_left=0)


def test_subject_shows_deadline_run_date_and_status():
    assert reminder_subject(EARLY, Status.WARNING) == (
        "[genomique] J-2 : run du 10/11/2026 — À surveiller"
    )
    assert reminder_subject(RUN_DAY, Status.OK).startswith("[genomique] Jour J")


def test_body_lists_every_check_and_asks_for_action_when_not_ok():
    checks = [Check("Espace disque", Status.WARNING, "8.0 Gio libres")]

    html = reminder_html(EARLY, checks, Status.WARNING)

    assert "le 10/11/2026 à 06:00 UTC, dans 2 jours" in html
    assert "Espace disque" in html and "8.0 Gio libres" in html
    assert "Corriger" in html


def test_body_escapes_check_details():
    """Un détail vient parfois d'une réponse réseau : il ne doit pas injecter de HTML."""
    html = reminder_html(EARLY, [Check("x", Status.WARNING, "<script>")], Status.WARNING)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_body_gives_the_start_time_rather_than_a_delay():
    """Un rappel rattrapé en retard ne doit pas annoncer « dans une heure »."""
    assert "(10/11/2026) à 06:00 UTC" in reminder_html(RUN_DAY, [], Status.OK)
    assert "demain" in reminder_html(Reminder(dt.date(2026, 11, 10), 1), [], Status.OK)
