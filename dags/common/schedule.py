"""Calendrier mensuel du pipeline : une seule source pour le run d'acquisition et ses rappels (UTC)."""
from __future__ import annotations

# L'archive ClinVar du mois paraît entre le 2 et le 6 : le 10 laisse une marge.
ACQUISITION_DAY = 10
ACQUISITION_HOUR = 6
ACQUISITION_CRON = f"0 {ACQUISITION_HOUR} {ACQUISITION_DAY} * *"

# J-2 en début de journée pour laisser le temps de corriger ; jour J une heure avant le run.
REMINDER_DAYS_BEFORE = 2
REMINDER_EARLY_CRON = f"0 8 {ACQUISITION_DAY - REMINDER_DAYS_BEFORE} * *"
REMINDER_DAY_OF_CRON = f"0 {ACQUISITION_HOUR - 1} {ACQUISITION_DAY} * *"
