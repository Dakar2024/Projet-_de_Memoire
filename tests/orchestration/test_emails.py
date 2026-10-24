import datetime as dt

from markupsafe import escape

from dags.common.emails import (
    LOGO_CID,
    Failure,
    catch_up_email,
    failure_email,
    reminder_email,
)
from dags.common.preflight import Check, Reminder, Status

EARLY = Reminder(run_date=dt.date(2026, 11, 10), days_left=2)
RUN_DAY = Reminder(run_date=dt.date(2026, 11, 10), days_left=0)


def test_every_pipeline_email_uses_the_application_design_with_its_logo():
    """Même gabarit que les e-mails de compte : carte blanche, logo intégré, pied de page."""
    for email in (
        reminder_email(EARLY, [], Status.OK),
        catch_up_email(SCHEDULED, STARTED, "2026-11-01"),
        failure_email(FAILURE),
    ):
        assert f'src="cid:{LOGO_CID}"' in email.html
        assert "Genomica" in email.html
        assert email.subject.startswith("[genomique] ")
        assert email.text.strip()


def test_reminder_subject_shows_deadline_run_date_and_status():
    assert reminder_email(EARLY, [], Status.WARNING).subject == (
        "[genomique] J-2 : run du 10/11/2026 — À surveiller"
    )
    assert reminder_email(RUN_DAY, [], Status.OK).subject.startswith("[genomique] Jour J")


def test_reminder_lists_every_check_and_asks_for_action_when_not_ok():
    checks = [Check("Espace disque", Status.WARNING, "8.0 Gio libres")]

    email = reminder_email(EARLY, checks, Status.WARNING)

    assert "le 10/11/2026 à 06:00 UTC, dans 2 jours" in email.html
    for body in (email.html, email.text):
        assert "Espace disque" in body and "8.0 Gio libres" in body and "À surveiller" in body
        assert "Corriger" in body


def test_reminder_says_nothing_to_do_when_every_check_is_ok():
    email = reminder_email(EARLY, [Check("Lac", Status.OK, "joignable")], Status.OK)

    assert "Rien à faire" in email.html


def test_reminder_escapes_check_details():
    """Un détail vient parfois d'une réponse réseau : il ne doit pas injecter de HTML."""
    html = reminder_email(EARLY, [Check("x", Status.WARNING, "<script>")], Status.WARNING).html

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_reminder_gives_the_start_time_rather_than_a_delay():
    """Un rappel rattrapé en retard ne doit pas annoncer « dans une heure »."""
    assert "(10/11/2026) à 06:00 UTC" in reminder_email(RUN_DAY, [], Status.OK).html
    assert "demain" in reminder_email(Reminder(dt.date(2026, 11, 10), 1), [], Status.OK).html


SCHEDULED = dt.datetime(2026, 11, 10, 6, tzinfo=dt.UTC)
STARTED = dt.datetime(2026, 11, 15, 9, 12, tzinfo=dt.UTC)


def test_catch_up_subject_names_the_missed_run():
    assert catch_up_email(SCHEDULED, STARTED, "2026-11-01").subject == (
        "[genomique] Rattrapage : run du 10/11/2026 lancé en retard"
    )


def test_catch_up_gives_the_missed_and_actual_start_times():
    html = catch_up_email(SCHEDULED, STARTED, "2026-11-01").html

    assert "10/11/2026 à 06:00 UTC" in html
    assert "15/11/2026 à 09:12 UTC" in html


def test_catch_up_names_the_month_actually_processed():
    """Machine éteinte le 10/11, rallumée le 03/12 : le run traite décembre, pas novembre."""
    email = catch_up_email(SCHEDULED, dt.datetime(2026, 12, 3, 8, tzinfo=dt.UTC), "2026-12-01")

    assert "Mois traité : 12/2026" in email.text
    assert "11/2026 n'est pas rattrapé" in email.text


def test_catch_up_says_nothing_is_skipped_within_the_same_month():
    html = catch_up_email(SCHEDULED, STARTED, "2026-11-01").html

    assert "Mois traité : 11/2026" in html
    assert "pas rattrapé" not in html


FAILURE = Failure(
    dag_id="dag_genomic_pipeline_brca",
    dag_description="Pipeline médaillon — Cancer du sein et de l'ovaire",
    task_id="bronze_to_silver",
    run_id="asset_triggered__2026-11-10T06:21:00",
    try_number=1,
    definitive=True,
    error="silver/clinvar_variant contient déjà le mois 2026-11 <brca>",
    log_url="http://localhost:8080/dags/dag_genomic_pipeline_brca/runs/x/tasks/bronze_to_silver",
)


def test_failure_subject_names_the_task_for_mail_filters():
    assert failure_email(FAILURE).subject == (
        "[genomique] Échec dag_genomic_pipeline_brca.bronze_to_silver"
    )


def test_failure_says_what_failed_in_plain_words():
    email = failure_email(FAILURE)

    assert FAILURE.dag_description in email.text
    assert str(escape(FAILURE.dag_description)) in email.html
    for body in (email.html, email.text):
        assert "asset_triggered__2026-11-10T06:21:00" in body


def test_a_definitive_failure_asks_to_fix_the_cause_before_relaunching():
    """AirflowFailException : une relance referait la même erreur."""
    text = failure_email(FAILURE).text

    assert "sans relance" in text
    assert "Corriger la cause" in text


def test_a_failure_after_retries_suggests_a_transient_cause():
    text = failure_email(Failure(**{**FAILURE.__dict__, "definitive": False, "try_number": 4})).text

    assert "après 4 essais" in text
    assert "plus tard" in text


def test_failure_shows_the_error_escaped_with_a_link_to_the_log():
    email = failure_email(FAILURE)

    assert "contient déjà le mois 2026-11 &lt;brca&gt;" in email.html
    assert f'href="{FAILURE.log_url}"' in email.html
    assert "Ouvrir le journal" in email.html
    assert FAILURE.log_url in email.text


def test_failure_points_to_the_recovery_procedure():
    assert "reference/procedure_reprise.md" in failure_email(FAILURE).text


def test_failure_without_log_url_has_no_button():
    email = failure_email(Failure(**{**FAILURE.__dict__, "log_url": None}))

    assert "Ouvrir le journal" not in email.html
