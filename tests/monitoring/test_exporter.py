import datetime as dt

import polars as pl
import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from monitoring.exporter import (
    AirflowClient,
    CachedCollector,
    Collection,
    Sample,
    collect_metrics,
    current_variants,
    disk_space,
    last_successful_runs,
    month_reclassifications,
    parse_last_success,
    partition_ages,
    rag_documents,
)
from transformations.silver_io import silver_table_uri
from transformations.silver_to_gold_analytique import gold_table_uri
from transformations.silver_to_gold_rag import documents_uri

TODAY = dt.date(2026, 10, 28)


def _seed_lake(tmp_path) -> str:
    lake = f"file://{tmp_path}/lake"
    pl.DataFrame({
        "alleleid": ["1", "1", "2", "3"],
        "panel": ["brca", "brca", "brca", "sickle"],
        "is_current": [False, True, True, True],
    }).write_delta(silver_table_uri("clinvar_variant", lake))
    pl.DataFrame({
        "doc_id": ["clinvar:1", "clinvar:2", "gene:BRCA1", "clinvar:3"],
        "doc_type": ["variant", "variant", "gene", "variant"],
        "panel": ["brca", "brca", "brca", "sickle"],
    }).write_delta(documents_uri(lake))
    pl.DataFrame({
        "alleleid": ["1", "2", "3"],
        "month": ["2026-10", "2026-10", "2026-10"],
        "panel": ["brca", "brca", "sickle"],
    }).write_delta(gold_table_uri("fact_variant", lake))
    pl.DataFrame({
        "gene_symbol": ["BRCA1", "BRCA2", "BRCA1", "HBB"],
        "month": ["2026-10", "2026-10", "2026-09", "2026-09"],
        "panel": ["brca", "brca", "brca", "sickle"],
        "reclassification_count": [2, 1, 5, 4],
    }).write_delta(gold_table_uri("agg_reclassifications_by_month", lake))
    for partition in ("raw/clinvar/dt=2026-09-01", "raw/clinvar/dt=2026-10-01",
                      "bronze/medgen/dt=2026-10-01/panel=brca"):
        (tmp_path / "lake" / partition).mkdir(parents=True)
        (tmp_path / "lake" / partition / "_SUCCESS").touch()
    (tmp_path / "lake" / "raw" / "clinvar" / "dt=2026-11-01").mkdir()   # interrompue
    return lake


def _by_labels(samples: list[Sample]) -> dict[tuple, float]:
    return {(s.name, tuple(sorted(s.labels.items()))): s.value for s in samples}


def test_current_variants_counts_only_current_rows_per_panel(tmp_path):
    samples = current_variants(_seed_lake(tmp_path))

    assert _by_labels(samples) == {
        ("genomics_current_variants", (("panel", "brca"),)): 2,
        ("genomics_current_variants", (("panel", "sickle"),)): 1,
    }


def test_rag_documents_counts_per_panel_and_document_type(tmp_path):
    samples = rag_documents(_seed_lake(tmp_path))

    assert _by_labels(samples) == {
        ("genomics_rag_documents", (("doc_type", "gene"), ("panel", "brca"))): 1,
        ("genomics_rag_documents", (("doc_type", "variant"), ("panel", "brca"))): 2,
        ("genomics_rag_documents", (("doc_type", "variant"), ("panel", "sickle"))): 1,
    }


def test_month_reclassifications_counts_the_latest_published_month_only(tmp_path):
    """Le mois vient de `fact_variant` : un mois sans reclassification vaut 0, pas le mois d'avant."""
    samples = month_reclassifications(_seed_lake(tmp_path))

    assert _by_labels(samples) == {
        ("genomics_month_reclassifications", (("panel", "brca"),)): 3,
        ("genomics_month_reclassifications", (("panel", "sickle"),)): 0,
    }


def test_partition_ages_use_the_latest_complete_partition_per_layer_and_source(tmp_path):
    samples = partition_ages(_seed_lake(tmp_path), TODAY)

    assert _by_labels(samples) == {
        ("genomics_partition_age_days", (("layer", "raw"), ("source", "clinvar"))): 27,
        ("genomics_partition_age_days", (("layer", "bronze"), ("source", "medgen"))): 27,
    }


def test_disk_space_reports_free_and_total_bytes(tmp_path):
    samples = _by_labels(disk_space({"data": tmp_path}))

    free = samples[("genomics_free_space_bytes", (("path", "data"),))]
    total = samples[("genomics_total_space_bytes", (("path", "data"),))]
    assert 0 < free <= total


def test_parse_last_success_returns_the_end_date_as_a_unix_timestamp():
    payload = {"dag_runs": [{"end_date": "2026-10-21T12:00:10.585132Z", "state": "success"}],
               "total_entries": 2}

    assert parse_last_success(payload) == pytest.approx(
        dt.datetime(2026, 10, 21, 12, 0, 10, 585132, tzinfo=dt.UTC).timestamp())


def test_parse_last_success_is_zero_when_the_dag_never_succeeded():
    """0 et non une série absente : « jamais réussi » doit déclencher la règle de silence."""
    assert parse_last_success({"dag_runs": [], "total_entries": 0}) == 0.0


def test_last_successful_runs_labels_each_dag():
    ends = {"dag_genomic_pipeline_brca": 1_761_000_000.0, "dag_genomic_pipeline_sickle": 0.0}

    samples = last_successful_runs(ends.__getitem__, list(ends))

    assert _by_labels(samples) == {
        ("genomics_last_successful_run_timestamp", (("dag", "dag_genomic_pipeline_brca"),)): 1_761_000_000.0,
        ("genomics_last_successful_run_timestamp", (("dag", "dag_genomic_pipeline_sickle"),)): 0.0,
    }


def test_collect_metrics_records_a_missing_table_without_raising(tmp_path):
    lake = _seed_lake(tmp_path)
    for entry in (tmp_path / "lake" / "gold" / "rag" / "documents").rglob("*"):
        if entry.is_file():
            entry.unlink()

    collection = collect_metrics(lake, {"data": tmp_path}, TODAY, lambda dag_id: 0.0, dag_ids=["d"])

    assert set(collection.errors) == {"rag_documents"}
    assert "current_variants" in collection.samples
    assert "rag_documents" not in collection.samples


def _scrape(collector: CachedCollector) -> dict[tuple, float]:
    registry = CollectorRegistry()
    registry.register(collector)
    text = generate_latest(registry).decode()
    return {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


def test_cached_collector_serves_a_valid_exposition():
    collector = CachedCollector(lambda: Collection(
        samples={"current_variants": [Sample("genomics_current_variants", {"panel": "brca"}, 2)]},
        errors={},
    ))
    collector.refresh()

    scraped = _scrape(collector)

    assert scraped[("genomics_current_variants", (("panel", "brca"),))] == 2
    assert scraped[("genomics_collection_ok", ())] == 1


def test_cached_collector_keeps_last_known_values_when_a_group_fails():
    """Le lac injoignable ne transforme pas une panne en angle mort : valeurs gardées, ok à 0."""
    results = iter([
        Collection(samples={"current_variants": [Sample("genomics_current_variants", {"panel": "brca"}, 2)]},
                   errors={}),
        Collection(samples={}, errors={"current_variants": "TableNotFoundError"}),
    ])
    collector = CachedCollector(lambda: next(results))
    collector.refresh()
    collector.refresh()

    scraped = _scrape(collector)

    assert scraped[("genomics_current_variants", (("panel", "brca"),))] == 2
    assert scraped[("genomics_collection_ok", ())] == 0


def test_cached_collector_survives_an_unexpected_exception():
    def boom() -> Collection:
        raise RuntimeError("panne")

    collector = CachedCollector(boom)
    collector.refresh()   # ne lève pas

    assert _scrape(collector)[("genomics_collection_ok", ())] == 0


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """Jeton à usage unique : le premier GET répond 401, le client doit en redemander un."""

    def __init__(self):
        self.tokens_issued = 0
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, json, timeout):
        self.tokens_issued += 1
        return _FakeResponse(201, {"access_token": f"t{self.tokens_issued}"})

    def get(self, url, params, headers, timeout):
        self.calls.append((url, params))
        if headers["Authorization"] == "Bearer t1":
            return _FakeResponse(401, {})
        return _FakeResponse(200, {"dag_runs": [{"end_date": "2026-10-21T12:00:00Z"}]})


def test_airflow_client_queries_the_last_success_and_renews_an_expired_token():
    session = _FakeSession()
    client = AirflowClient("http://airflow-apiserver:8080", "monitoring", "secret", session=session)

    end = client.last_success("dag_genomic_pipeline_brca")

    assert end == dt.datetime(2026, 10, 21, 12, tzinfo=dt.UTC).timestamp()
    assert session.tokens_issued == 2
    url, params = session.calls[-1]
    assert url == "http://airflow-apiserver:8080/api/v2/dags/dag_genomic_pipeline_brca/dagRuns"
    assert params == {"state": "success", "order_by": "-end_date", "limit": 1}
