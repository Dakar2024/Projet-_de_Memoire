"""DAG manuel qui échoue exprès : vérifie de bout en bout qu'une alerte d'échec arrive par e-mail."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from dags.common.alerting import alert_args

with DAG(
    dag_id="dag_test_alerte",
    description="Échec volontaire pour tester l'envoi d'alerte (à relancer après tout changement SMTP)",
    # Jamais planifié : se déclenche à la main, `airflow dags trigger dag_test_alerte`.
    schedule=None,
    start_date=dt.datetime(2026, 1, 1),
    catchup=False,
    is_paused_upon_creation=True,
    default_args={**alert_args(), "retries": 0},
    tags=["maintenance", "alerte"],
) as dag:

    @task(task_id="echec_volontaire")
    def echec_volontaire() -> None:
        """Échoue sans relance pour déclencher l'alerte."""
        raise AirflowFailException("Échec volontaire : test de l'alerte e-mail.")

    echec_volontaire()
