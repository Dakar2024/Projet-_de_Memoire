"""Contrôles avant le run mensuel : chacun rend un état et ne lève jamais (le rappel doit partir)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

import requests

from dags.common.schedule import ACQUISITION_DAY, ACQUISITION_HOUR
from ingestion.clinvar import archive_url_for, archive_version_for
from ingestion.maintenance import MIN_FREE_BYTES

# Un mois ajoute ~1,3 Go au lac et le téléchargement ClinVar ~0,5 Go : 10 Gio laissent plusieurs mois.
RECOMMENDED_FREE_BYTES = 10 * 1024**3


class Status(str, Enum):
    OK = "ok"
    WARNING = "attention"
    BLOCKING = "bloquant"


_SEVERITY = {Status.OK: 0, Status.WARNING: 1, Status.BLOCKING: 2}


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


@dataclass(frozen=True)
class Reminder:
    run_date: dt.date
    days_left: int

    @property
    def label(self) -> str:
        return "Jour J" if self.days_left == 0 else f"J-{self.days_left}"

    @property
    def is_run_day(self) -> bool:
        return self.days_left == 0

    @property
    def archive_version(self) -> str:
        return archive_version_for(self.run_date.isoformat())


def reminder_for(today: dt.date) -> Reminder:
    """Renvoie le prochain run d'acquisition (aujourd'hui compris) et le nombre de jours restants."""
    run_date = today.replace(day=ACQUISITION_DAY)
    if today.day > ACQUISITION_DAY:
        year, month = divmod(today.month, 12)
        run_date = dt.date(today.year + year, month + 1, ACQUISITION_DAY)
    return Reminder(run_date=run_date, days_left=(run_date - today).days)


def reminder_at(scheduled: dt.datetime, now: dt.datetime) -> Reminder | None:
    """Rappel du run visé par l'échéance `scheduled`, compté depuis `now` ; `None` si ce run a démarré.

    Même avec `catchup=False`, Airflow exécute la dernière échéance passée (sortie de pause,
    machine rallumée) : un rappel en retard garde son run cible, pas son étiquette (J-2 devient J-1).
    """
    run_date = reminder_for(scheduled.date()).run_date
    run_start = dt.datetime.combine(run_date, dt.time(ACQUISITION_HOUR), tzinfo=dt.UTC)
    if now >= run_start:
        return None
    return Reminder(run_date=run_date, days_left=(run_date - now.astimezone(dt.UTC).date()).days)


def utcnow() -> dt.datetime:
    """Heure courante en UTC, isolée pour que les tests la figent."""
    return dt.datetime.now(dt.UTC)


def probe_clinvar_archive(version: str, session: requests.Session | None = None) -> int | None:
    """Renvoie le code HTTP d'un HEAD sur l'archive ClinVar du mois, `None` si NCBI est injoignable."""
    try:
        response = (session or requests).head(
            archive_url_for(f"{version}-01"), allow_redirects=True, timeout=30
        )
        return response.status_code
    except requests.RequestException:
        return None


def check_clinvar_archive(http_status: int | None, version: str, is_run_day: bool) -> Check:
    """L'archive manquante n'est bloquante que le jour du run : avant, NCBI peut encore la publier."""
    name = f"Archive ClinVar {version}"
    if http_status == 200:
        return Check(name, Status.OK, "publiée")
    if http_status == 404:
        if is_run_day:
            return Check(name, Status.BLOCKING, "absente : le téléchargement du run échouera")
        return Check(name, Status.WARNING, "pas encore publiée ; le run échouera si elle manque le jour J")
    if http_status is None:
        return Check(name, Status.WARNING, "NCBI injoignable, contrôle impossible")
    return Check(name, Status.WARNING, f"réponse HTTP {http_status} inattendue")


def check_free_space(
    free_bytes: int,
    recommended: int = RECOMMENDED_FREE_BYTES,
    minimum: int = MIN_FREE_BYTES,
) -> Check:
    """Sous `minimum`, le run refuse de démarrer (`ensure_free_space`) ; sous `recommended`, il faut anticiper."""
    detail = f"{_gio(free_bytes)} libres (recommandé : {_gio(recommended)})"
    if free_bytes < minimum:
        return Check("Espace disque", Status.BLOCKING, f"{detail} : le run échouera")
    if free_bytes < recommended:
        return Check("Espace disque", Status.WARNING, f"{detail} : libérer de la place")
    return Check("Espace disque", Status.OK, detail)


def check_lake(reachable: bool) -> Check:
    if reachable:
        return Check("Lac MinIO", Status.OK, "joignable")
    return Check("Lac MinIO", Status.BLOCKING, "injoignable : aucune couche ne pourra être écrite")


def overall(checks: list[Check]) -> Status:
    """Renvoie l'état le plus grave des contrôles."""
    return max((c.status for c in checks), key=_SEVERITY.__getitem__, default=Status.OK)


def _gio(n: int) -> str:
    return f"{n / 1024**3:.1f} Gio"
