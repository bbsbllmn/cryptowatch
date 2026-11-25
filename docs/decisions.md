# Design decisions

**ADR-001 Batch, daily, digest.** One 08:00 Lagos snapshot, 3 API calls/day (free Demo key: ~30 calls/min, 10k/month). Cost and API budget are trivial; trade-off: intra-day moves that reverse are missed.

**ADR-002 Python + dbt + BigQuery, not PySpark.** ~500 rows/day. Spark would be overhead. Rules live in SQL where analysts can read and test them; extraction is plain Python with an injected HTTP client.

**ADR-003 Tiered thresholds, in a seed.** A single ±85% rule never fires on large caps. Tiers and volume floors are data (`alert_thresholds.csv`), changeable by PR with an audit trail and no code change. 85% remains the MICRO tier default as requested.

**ADR-004 Volume floor.** Thin markets produce huge percentage moves from tiny trades; the floor is the cheapest effective guard against false alerts.

**ADR-005 "Newly listed" = snapshot diff.** The new-listings endpoint is not on the free plan. Cold start would flag all 500 coins, so trending/new rules stay silent until 3 days of history exist, and the first snapshot is a baseline. Honest naming: a coin that merely climbed into the top 500 is `NEW_IN_UNIVERSE` MEDIUM; HIGH needs a recent all-time-low date.

**ADR-006 Repeat suppression.** Same coin + rule within 3 days is stored (`is_repeat`) but not notified, so one pump does not page people every morning. Known limit: a continuing move that doubles in size is not escalated.

**ADR-007 Idempotency end to end.** Raw landing is reused on retry (no second API call, so retries do not burn quota); loads replace one day's partition; dbt models are pure functions of snapshots; sends go through a ledger keyed by (date, channel). Sends are at-least-once: a crash between the webhook call and the ledger write can duplicate once.

**ADR-008 Airflow on Composer vs cheaper.** Composer is the managed answer, but for one daily DAG it dominates the bill. A small self-managed Airflow VM, or Cloud Scheduler + Cloud Run job, would do the same work for a fraction of the cost; the DAG logic lives in plain functions (`tasks.py`) so it moves unchanged.

**ADR-009 No backfill from the API.** The free API serves current data only. The extract task refuses to create a snapshot for a past date; landed days can be re-processed from GCS (versioned bucket).

**ADR-010 The model is never a trust boundary.** Explanation text must pass: every number equals a supplied fact rounded or truncated to the precision shown; no advice phrases; no links; length cap. Untrusted coin names are sanitised and escaped for Slack and HTML; Slack webhook host is pinned; images and links must be https. Failure of any check, or an outage, falls back to a template: the alert is never lost.

**ADR-011 Secrets.** CoinGecko key in a header (not a URL), all credentials in Secret Manager, never in Terraform state or logs; error messages from channels do not echo URLs.
