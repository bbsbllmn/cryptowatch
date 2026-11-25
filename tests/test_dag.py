import pytest

pytest.importorskip("airflow")
from pathlib import Path  # noqa: E402

from airflow.models import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parents[1] / "dags"


@pytest.fixture(scope="module")
def dag():
    bag = DagBag(dag_folder=str(DAGS), include_examples=False)
    assert bag.import_errors == {}, bag.import_errors
    return bag.dags["crypto_daily_digest"]


def test_schedule_and_safety_properties(dag):
    assert str(dag.timezone) == "Africa/Lagos" and dag.catchup is False and dag.max_active_runs == 1
    assert dag.timetable.summary == "0 8 * * *"
    assert dag.default_args["owner"] and dag.default_args["on_failure_callback"] and dag.tags


def test_wiring_alerts_cannot_be_sent_before_data_is_loaded_and_tested(dag):
    send_up = dag.get_task("send").get_flat_relative_ids(upstream=True)
    assert {"extract_markets", "extract_trending", "load_markets", "load_trending", "dbt_build", "build_digest"} <= send_up
    assert dag.get_task("audit").trigger_rule == "all_done"
    assert "dbt_build" in dag.get_task("build_digest").upstream_task_ids


def test_loads_replace_a_single_partition(dag):
    for t in ("load_markets", "load_trending"):
        op = dag.get_task(t)
        assert op.write_disposition == "WRITE_TRUNCATE" and "$" in op.destination_project_dataset_table


def test_taskflow_tasks_resolve_snapshot_date_from_interval_context(dag, monkeypatch):
    import inspect

    import pendulum

    task_ids = ("extract_markets", "extract_trending", "build_digest", "send", "audit")
    for task_id in task_ids:
        callable_ = dag.get_task(task_id).python_callable
        assert "snapshot_date" not in inspect.signature(callable_).parameters

    interval_end = pendulum.datetime(2026, 11, 25, 23, 30, tz="UTC")
    monkeypatch.setattr(
        "airflow.operators.python.get_current_context",
        lambda: {"data_interval_end": interval_end},
    )
    date_helper = dag.get_task("extract_markets").python_callable.__globals__["_snapshot_date"]
    assert date_helper() == "2026-11-26"
