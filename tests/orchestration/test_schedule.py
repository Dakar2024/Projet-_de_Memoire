import datetime as dt

import pytest

from dags.common.schedule import CATCH_UP_TOLERANCE, catch_up_delay

SCHEDULED = dt.datetime(2026, 11, 10, 6, tzinfo=dt.UTC)


@pytest.mark.parametrize("late_by", [dt.timedelta(0), dt.timedelta(minutes=5), CATCH_UP_TOLERANCE])
def test_a_run_started_within_the_tolerance_is_on_time(late_by):
    """Le scheduler démarre un run quelques secondes à minutes après l'échéance : ce n'est pas un rattrapage."""
    assert catch_up_delay(SCHEDULED, SCHEDULED + late_by) is None


def test_a_run_started_after_the_tolerance_is_a_catch_up():
    """Machine éteinte le 10, rallumée le 15 : Airflow lance l'échéance manquée au redémarrage."""
    started = dt.datetime(2026, 11, 15, 9, 12, tzinfo=dt.UTC)

    assert catch_up_delay(SCHEDULED, started) == started - SCHEDULED
