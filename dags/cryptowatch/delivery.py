"""Idempotent delivery. A retry or a re-run of the same digest must not message people twice, so every
(digest date, channel) is checked against a ledger before sending and recorded after. This is at-least-once
(a crash between send and record can duplicate once); exactly-once is impossible across an external webhook."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

log = logging.getLogger(__name__)


class Ledger(Protocol):
    def already_sent(self, ds: str, channel: str) -> bool: ...
    def record(self, ds: str, channel: str, status: str, alert_count: int, detail: str = "") -> None: ...


class InMemoryLedger:
    def __init__(self):
        self.rows = []

    def already_sent(self, ds, channel):
        return any(r["ds"] == ds and r["channel"] == channel and r["status"] == "SENT" for r in self.rows)

    def record(self, ds, channel, status, alert_count, detail=""):
        self.rows.append({"ds": ds, "channel": channel, "status": status, "alert_count": alert_count, "detail": detail})


class BigQueryLedger:
    def __init__(self, client, project: str, ops_dataset: str):
        self.c, self.table = client, f"{project}.{ops_dataset}.notification_ledger"

    def already_sent(self, ds, channel):
        from google.cloud import bigquery
        job = self.c.query(f"select count(*) n from `{self.table}` where ds = @ds and channel = @ch and status = 'SENT'",
                           job_config=bigquery.QueryJobConfig(query_parameters=[
                               bigquery.ScalarQueryParameter("ds", "DATE", ds),
                               bigquery.ScalarQueryParameter("ch", "STRING", channel)]))
        return list(job.result())[0]["n"] > 0

    def record(self, ds, channel, status, alert_count, detail=""):
        errs = self.c.insert_rows_json(self.table, [{
            "ds": ds, "channel": channel, "status": status, "alert_count": alert_count,
            "detail": detail[:500], "attempted_at": datetime.now(timezone.utc).isoformat()}])
        if errs:
            raise RuntimeError(f"ledger insert failed: {errs}")


def deliver(channel, digest, ledger: Ledger) -> str:
    """Returns SENT | SKIPPED_ALREADY_SENT. Raises on failure (after recording it) so Airflow retries."""
    if ledger.already_sent(digest.ds, channel.name):
        log.info("%s digest for %s already sent; skipping", channel.name, digest.ds)
        return "SKIPPED_ALREADY_SENT"
    try:
        channel.send(digest)
    except Exception as exc:
        ledger.record(digest.ds, channel.name, "FAILED", len(digest.alerts), type(exc).__name__)
        raise
    ledger.record(digest.ds, channel.name, "SENT", len(digest.alerts))
    return "SENT"
