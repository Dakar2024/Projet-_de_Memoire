"""Calendrier mensuel du pipeline : une seule source pour le run d'acquisition et ses rappels (UTC)."""
from __future__ import annotations

import datetime as dt

# L'archive ClinVar du mois paraît entre le 2 et le 6 : le 10 laisse une marge.
ACQUISITION_DAY = 10
ACQUISITION_HOUR = 6
ACQUISITION_CRON = f"0 {ACQUISITION_HOUR} {ACQUISITION_DAY} * *"

# J-2 en début de journée pour laisser le temps de corriger ; jour J une heure avant le run.
REMINDER_DAYS_BEFORE = 2
REMINDER_EARLY_CRON = f"0 8 {ACQUISITION_DAY - REMINDER_DAYS_BEFORE} * *"
REMINDER_DAY_OF_CRON = f"0 {ACQUISITION_HOUR - 1} {ACQUISITION_DAY} * *"

# Au-delà, le run planifié n'a pas démarré à l'échéance (machine ou pile arrêtée) : Airflow le rattrape au redémarrage.
CATCH_UP_TOLERANCE = dt.timedelta(hours=1)


def catch_up_delay(scheduled: dt.datetime, started: dt.datetime) -> dt.timedelta | None:
    """Renvoie le retard d'un run planifié parti après la tolérance, `None` s'il est parti à l'heure."""
    delay = started - scheduled
    return delay if delay > CATCH_UP_TOLERANCE else None
