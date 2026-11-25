"""
crypto_daily_digest - 08:00 Africa/Lagos, once a day.

    extract markets (top 500) ─┐                                    ┌─> send slack ─┐
                               ├─> load raw ─> dbt build ─> digest ─┤               ├─> audit
    extract trending ──────────┘   (partition     (seed, models,    └─> send email ─┘
                                    replace)       tests)       (AI explainer, mapped per channel)

Properties
  * Batch by design: one daily snapshot, 3 API calls (free Demo-key friendly), alerts as a digest.
  * Idempotent: raw landing is reused on retry (no second API call), loads replace one partition, dbt is a pure
    function of the snapshots, and the notification ledger prevents double sends.
  * Bad data stops the line BEFORE alerting (contract gate in extract; dbt tests before the digest).
  * Snapshot date = Lagos date of data_interval_end (the run fires at the end of the interval).
  * No catch-up: the free API serves current data only, so past days cannot be rebuilt from the API.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.exceptions import AirflowFailException
from airflow.operators.bash import BashOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.utils.trigger_rule import TriggerRule

from cryptowatch.config import BUSINESS_TZ, SNAPSHOT_DATE, settings

cfg = settings()
DS_NODASH = "{{ data_interval_end.in_timezone('" + BUSINESS_TZ + "').strftime('%Y%m%d') }}"


def _alert_failure(context) -> None:
    import requests

    from cryptowatch.secrets import get_secret
    ti = context["task_instance"]
    try:
        url = get_secret(cfg.project, cfg.slack_secret)
        requests.post(url, json={"text": f":red_circle: crypto_daily_digest `{ti.task_id}` failed (try {ti.try_number}): {ti.log_url}"},
                      timeout=10)
    except Exception:  # noqa: BLE001  alerting must never mask the original failure
        pass


def _snapshot_date() -> str:
    from airflow.operators.python import get_current_context

    return get_current_context()["data_interval_end"].in_timezone(BUSINESS_TZ).strftime("%Y-%m-%d")


def _store():
    from airflow.providers.google.cloud.hooks.gcs import GCSHook

    class GCSStore:
        h = GCSHook()

        def exists(self, key): return self.h.exists(cfg.lake_bucket, key)
        def read(self, key): return self.h.download(cfg.lake_bucket, key).decode()
        def write(self, key, text): self.h.upload(cfg.lake_bucket, key, data=text, mime_type="application/x-ndjson")
    return GCSStore()


def _bq():
    from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
    return BigQueryHook(location=cfg.bq_location).get_client(project_id=cfg.project)


@dag(
    dag_id="crypto_daily_digest", schedule="0 8 * * *", start_date=pendulum.datetime(2026, 11, 1, tz=BUSINESS_TZ),
    catchup=False, max_active_runs=1, dagrun_timeout=timedelta(hours=2), tags=["cryptowatch", "alerts"],
    default_args={"owner": "data-engineering", "retries": 2, "retry_delay": timedelta(minutes=5),
                  "retry_exponential_backoff": True, "on_failure_callback": _alert_failure},
    doc_md=__doc__,
)
def crypto_daily_digest():
    def make_extract(kind: str):
        @task(task_id=f"extract_{kind}")
        def _extract():
            from cryptowatch.coingecko import CoinGeckoClient
            from cryptowatch.quality import DataContractError
            from cryptowatch.secrets import get_secret
            from cryptowatch.tasks import extract

            snapshot_date = _snapshot_date()
            today = pendulum.now(BUSINESS_TZ).strftime("%Y-%m-%d")
            try:
                client = CoinGeckoClient(cfg.coingecko_base_url, get_secret(cfg.project, cfg.coingecko_key_secret))
                return extract(kind, snapshot_date, today, client, _store(), cfg.raw_path(snapshot_date, kind),
                               min_rows=cfg.min_universe_rows)
            except DataContractError as exc:           # bad data / impossible replay: retrying cannot help
                raise AirflowFailException(str(exc)) from None
        return _extract()

    def make_load(kind: str, schema):
        from cryptowatch.tasks import bq_schema
        return GCSToBigQueryOperator(
            task_id=f"load_{kind}", bucket=cfg.lake_bucket,
            source_objects=[cfg.raw_path(SNAPSHOT_DATE, kind)], source_format="NEWLINE_DELIMITED_JSON",
            destination_project_dataset_table=f"{cfg.project}.{cfg.ds_raw}.raw_{kind}${DS_NODASH}",
            schema_fields=bq_schema(schema), write_disposition="WRITE_TRUNCATE",      # replaces only this day's partition
            create_disposition="CREATE_IF_NEEDED", time_partitioning={"type": "DAY", "field": "snapshot_date"},
            location=cfg.bq_location, max_bad_records=0)

    from cryptowatch.tasks import MARKETS_SCHEMA, TRENDING_SCHEMA
    ext_m, ext_t = make_extract("markets"), make_extract("trending")
    load_m, load_t = make_load("markets", MARKETS_SCHEMA), make_load("trending", TRENDING_SCHEMA)

    dbt_build = BashOperator(
        task_id="dbt_build", cwd=cfg.dbt_project_dir,
        bash_command="dbt build --target {{ params.target }} --vars '{\"ds\": \"" + SNAPSHOT_DATE + "\"}' --fail-fast",
        params={"target": cfg.dbt_target}, env={"DBT_PROFILES_DIR": cfg.dbt_project_dir, "CW_PROJECT": cfg.project},
        append_env=True, execution_timeout=timedelta(minutes=30))

    @task
    def build_digest() -> dict:
        from cryptowatch.digest import ALERTS_SQL, UNIVERSE_SQL, build_digest as assemble
        from cryptowatch.llm import AnthropicLLM
        from cryptowatch.secrets import get_secret

        snapshot_date = _snapshot_date()
        c = _bq()
        rows = [dict(r) for r in c.query(ALERTS_SQL.format(project=cfg.project, gold=cfg.ds_gold, ds=snapshot_date)).result()]
        scanned = list(c.query(UNIVERSE_SQL.format(project=cfg.project, gold=cfg.ds_gold, ds=snapshot_date)).result())[0]["n"]
        if scanned == 0:
            raise AirflowFailException(f"no coins in gold for {snapshot_date}: refusing to send an 'all quiet' digest")
        try:
            llm = AnthropicLLM(cfg.ai_model, api_key=get_secret(cfg.project, cfg.anthropic_secret))
        except Exception:  # noqa: BLE001  no key / SDK problem => templates only
            llm = None
        d = assemble(snapshot_date, rows[:200], scanned, llm, cfg.max_explained)
        return json.loads(json.dumps(asdict(d), default=str))

    @task(max_active_tis_per_dag=2)
    def send(channel: str, digest: dict) -> str:
        from cryptowatch.channels import EmailChannel, SlackChannel
        from cryptowatch.delivery import BigQueryLedger, deliver
        from cryptowatch.formatters import Digest
        from cryptowatch.secrets import get_secret
        d = Digest(**digest)
        if channel == "slack":
            ch = SlackChannel(get_secret(cfg.project, cfg.slack_secret), max_alerts=cfg.max_slack_alerts)
        elif channel == "email":
            ch = EmailChannel(json.loads(get_secret(cfg.project, cfg.smtp_secret)))
        else:
            raise AirflowFailException(f"unknown channel {channel!r}")
        return deliver(ch, d, BigQueryLedger(_bq(), cfg.project, cfg.ds_ops))

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def audit(dag_run=None) -> None:
        snapshot_date = _snapshot_date()
        states = {t.task_id: t.state for t in dag_run.get_task_instances() if t.task_id != "audit"}
        failed = sorted(k for k, v in states.items() if v in ("failed", "upstream_failed"))
        errs = _bq().insert_rows_json(f"{cfg.project}.{cfg.ds_ops}.pipeline_runs", [{
            "ds": snapshot_date, "run_id": dag_run.run_id, "status": "FAILED" if failed else "SUCCESS",
            "failed_tasks": failed, "finished_at": pendulum.now("UTC").isoformat()}])
        if errs:
            raise RuntimeError(f"audit insert failed: {errs}")

    digest = build_digest()
    sends = send.partial(digest=digest).expand(channel=[c.strip() for c in cfg.channels.split(",") if c.strip()])
    ext_m >> load_m
    ext_t >> load_t
    [load_m, load_t] >> dbt_build >> digest
    sends >> audit()


crypto_daily_digest()
