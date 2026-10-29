"""Exportateur Prometheus : volumes, fraîcheur et espace disque du lac, derniers runs Airflow réussis.

La collecte est faite de fonctions pures sur le lac ; `CachedCollector` sert les dernières valeurs
connues, si bien qu'un lac injoignable ne transforme pas une panne en angle mort.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import polars as pl
import requests
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector

from ingestion.config import BRONZE, PANEL_GENES, RAW
from ingestion.storage import find_complete_partitions, layer_uri, storage_options
from transformations.silver_io import silver_table_uri
from transformations.silver_to_gold_analytique import gold_table_uri
from transformations.silver_to_gold_rag import documents_uri

log = logging.getLogger(__name__)

# DAG mensuels surveillés par la règle de silence ; dag_acquisition_sources est manuel.
PIPELINE_DAG_IDS = tuple(f"dag_genomic_pipeline_{panel}" for panel in PANEL_GENES)

_HELP = {
    "genomics_current_variants": "Variants ClinVar courants (is_current) du Silver, par panel",
    "genomics_rag_documents": "Documents RAG du Gold, par panel et type",
    "genomics_month_reclassifications": "Transitions SCD2 du dernier mois publié en Gold, par panel",
    "genomics_partition_age_days": "Âge en jours de la dernière partition complète (_SUCCESS)",
    "genomics_free_space_bytes": "Espace libre du système de fichiers monté",
    "genomics_total_space_bytes": "Taille du système de fichiers monté",
    "genomics_last_successful_run_timestamp": "Fin du dernier run réussi (secondes Unix, 0 = jamais)",
}


class Sample(NamedTuple):
    name: str
    labels: dict[str, str]
    value: float


@dataclass(frozen=True)
class Collection:
    """Échantillons des groupes réussis ; message d'erreur des groupes en échec."""

    samples: dict[str, list[Sample]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _read_delta(uri: str, columns: list[str]) -> pl.DataFrame:
    return pl.read_delta(uri, columns=columns, storage_options=storage_options(uri))


def current_variants(lake_uri: str | None) -> list[Sample]:
    variants = _read_delta(silver_table_uri("clinvar_variant", lake_uri), ["panel", "is_current"])
    counts = variants.filter(pl.col("is_current")).group_by("panel").len()
    return [Sample("genomics_current_variants", {"panel": panel}, n) for panel, n in counts.iter_rows()]


def rag_documents(lake_uri: str | None) -> list[Sample]:
    counts = _read_delta(documents_uri(lake_uri), ["panel", "doc_type"]).group_by("panel", "doc_type").len()
    return [
        Sample("genomics_rag_documents", {"panel": panel, "doc_type": doc_type}, n)
        for panel, doc_type, n in counts.iter_rows()
    ]


def month_reclassifications(lake_uri: str | None) -> list[Sample]:
    """Le mois vient de `fact_variant` : un mois publié sans transition vaut 0."""
    months = _read_delta(gold_table_uri("fact_variant", lake_uri), ["panel", "month"]).group_by("panel").agg(
        pl.col("month").max()
    )
    reclassifications = _read_delta(
        gold_table_uri("agg_reclassifications_by_month", lake_uri), ["panel", "month", "reclassification_count"]
    )
    counts = (
        months.join(reclassifications, on=["panel", "month"], how="left")
        .group_by("panel")
        .agg(pl.col("reclassification_count").sum())
    )
    return [
        Sample("genomics_month_reclassifications", {"panel": panel}, n) for panel, n in counts.iter_rows()
    ]


def partition_ages(lake_uri: str | None, today: dt.date) -> list[Sample]:
    """Âge de la dernière partition complète par couche et source ; une partition interrompue ne compte pas."""
    samples = []
    for layer in (RAW, BRONZE):
        root = layer_uri(layer, lake_uri)
        latest: dict[str, dt.date] = {}
        for partition in find_complete_partitions(root):
            source, date_part, *_ = partition.removeprefix(f"{root}/").split("/")
            date = dt.date.fromisoformat(date_part.removeprefix("dt="))
            latest[source] = max(date, latest.get(source, date))
        samples += [
            Sample("genomics_partition_age_days", {"layer": layer, "source": source}, (today - date).days)
            for source, date in latest.items()
        ]
    return samples


def disk_space(paths: Mapping[str, Path]) -> list[Sample]:
    """Espace du système de fichiers réellement monté ; celui de MinIO (vhdx de WSL) surestime C:."""
    samples = []
    for name, path in paths.items():
        usage = shutil.disk_usage(path)
        samples += [
            Sample("genomics_free_space_bytes", {"path": name}, usage.free),
            Sample("genomics_total_space_bytes", {"path": name}, usage.total),
        ]
    return samples


def parse_last_success(payload: dict) -> float:
    """Fin du run réussi le plus récent, 0 s'il n'y en a aucun (« jamais » doit déclencher l'alerte)."""
    runs = payload.get("dag_runs", [])
    if not runs:
        return 0.0
    return dt.datetime.fromisoformat(runs[0]["end_date"]).timestamp()


def last_successful_runs(last_success: Callable[[str], float], dag_ids: Sequence[str]) -> list[Sample]:
    return [
        Sample("genomics_last_successful_run_timestamp", {"dag": dag_id}, last_success(dag_id))
        for dag_id in dag_ids
    ]


class AirflowClient:
    """API REST d'Airflow, avec un compte `viewer` : l'exportateur ne peut rien déclencher."""

    def __init__(self, base_url: str, username: str, password: str, session=None, timeout: int = 10):
        self._base_url = base_url.rstrip("/")
        self._credentials = {"username": username, "password": password}
        self._session = session or requests.Session()
        self._timeout = timeout
        self._token: str | None = None

    def _new_token(self) -> str:
        response = self._session.post(
            f"{self._base_url}/auth/token", json=self._credentials, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def last_success(self, dag_id: str) -> float:
        url = f"{self._base_url}/api/v2/dags/{dag_id}/dagRuns"
        params = {"state": "success", "order_by": "-end_date", "limit": 1}
        # Un jeton expiré répond 401 : on en redemande un, une seule fois.
        for attempt in range(2):
            if self._token is None:
                self._token = self._new_token()
            response = self._session.get(
                url, params=params, headers={"Authorization": f"Bearer {self._token}"}, timeout=self._timeout
            )
            if response.status_code == 401 and attempt == 0:
                self._token = None
                continue
            response.raise_for_status()
            return parse_last_success(response.json())
        raise AssertionError("unreachable")


def collect_metrics(
    lake_uri: str | None,
    data_paths: Mapping[str, Path],
    today: dt.date,
    last_success: Callable[[str], float],
    dag_ids: Sequence[str] = PIPELINE_DAG_IDS,
) -> Collection:
    """Collecte chaque groupe isolément : une table absente n'empêche pas les autres d'être servis."""
    groups: dict[str, Callable[[], list[Sample]]] = {
        "current_variants": lambda: current_variants(lake_uri),
        "rag_documents": lambda: rag_documents(lake_uri),
        "month_reclassifications": lambda: month_reclassifications(lake_uri),
        "partition_ages": lambda: partition_ages(lake_uri, today),
        "disk_space": lambda: disk_space(data_paths),
        "last_successful_runs": lambda: last_successful_runs(last_success, dag_ids),
    }
    collection = Collection()
    for group, collect in groups.items():
        try:
            collection.samples[group] = collect()
        except Exception as exc:  # noqa: BLE001 — toute erreur de lecture devient genomics_collection_ok = 0
            log.warning("collecte %s en échec : %r", group, exc)
            collection.errors[group] = repr(exc)
    return collection


class CachedCollector(Collector):
    """Sert les dernières valeurs connues de chaque groupe ; `genomics_collection_ok` dit si elles sont fraîches."""

    def __init__(self, collect: Callable[[], Collection]):
        self._collect = collect
        self._samples: dict[str, list[Sample]] = {}
        self._ok = 0.0
        self._last_collection = 0.0
        self._lock = threading.Lock()

    def refresh(self) -> None:
        try:
            collection = self._collect()
        except Exception:  # l'exportateur ne meurt jamais d'une collecte
            log.exception("collecte en échec")
            collection = Collection(errors={"*": "exception"})
        with self._lock:
            self._samples.update(collection.samples)
            self._ok = 0.0 if collection.errors else 1.0
            self._last_collection = time.time()

    def collect(self) -> Iterator[GaugeMetricFamily]:
        with self._lock:
            samples = [sample for group in self._samples.values() for sample in group]
            ok, last_collection = self._ok, self._last_collection
        families: dict[str, GaugeMetricFamily] = {}
        for sample in samples:
            if sample.name not in families:
                families[sample.name] = GaugeMetricFamily(
                    sample.name, _HELP[sample.name], labels=sorted(sample.labels)
                )
            families[sample.name].add_metric([sample.labels[k] for k in sorted(sample.labels)], sample.value)
        yield from families.values()
        yield GaugeMetricFamily("genomics_collection_ok", "1 si la dernière collecte a tout lu, 0 sinon", value=ok)
        yield GaugeMetricFamily(
            "genomics_last_collection_timestamp", "Fin de la dernière collecte (secondes Unix)", value=last_collection
        )


def serve(port: int = 9102, interval_seconds: int = 600) -> None:
    """Recalcule toutes les dix minutes ; Prometheus lit le cache à chaque collecte."""
    from prometheus_client import start_http_server

    airflow = AirflowClient(
        os.environ["AIRFLOW_API_URL"],
        os.environ["AIRFLOW_MONITORING_USER"],
        os.environ["AIRFLOW_MONITORING_PASSWORD"],
    )
    data_paths = {"data": Path(os.environ.get("EXPORTER_DATA_PATH", "/opt/projet/data"))}
    collector = CachedCollector(lambda: collect_metrics(
        os.environ.get("LAKE_URI"), data_paths, dt.datetime.now(dt.UTC).date(), airflow.last_success,
    ))
    REGISTRY.register(collector)
    start_http_server(port)
    log.info("exportateur à l'écoute sur :%d, collecte toutes les %d s", port, interval_seconds)
    while True:
        collector.refresh()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    serve(int(os.environ.get("EXPORTER_PORT", "9102")))
