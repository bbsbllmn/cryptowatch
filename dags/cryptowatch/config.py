"""Configuration from environment variables (no Airflow Variable lookups at DAG-parse time)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

BUSINESS_TZ = "Africa/Lagos"
# Digest runs at 08:00 Lagos, so the run's snapshot date is the Lagos date of data_interval_END
# (the moment the run fires), not the start of the interval.
SNAPSHOT_DATE = "{{ data_interval_end.in_timezone('" + BUSINESS_TZ + "').strftime('%Y-%m-%d') }}"


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(f"CW_{name}", default)
    if v is None:
        raise RuntimeError(f"Missing required environment variable CW_{name}")
    return v


@dataclass(frozen=True)
class Settings:
    project: str = field(default_factory=lambda: _env("PROJECT", "crypto-dev-project"))
    region: str = field(default_factory=lambda: _env("REGION", "europe-west1"))
    bq_location: str = field(default_factory=lambda: _env("BQ_LOCATION", "EU"))
    lake_bucket: str = field(default_factory=lambda: _env("LAKE_BUCKET", "crypto-dev-lake"))
    ds_raw: str = field(default_factory=lambda: _env("DATASET_RAW", "crypto_raw"))
    ds_staging: str = field(default_factory=lambda: _env("DATASET_STAGING", "crypto_staging"))
    ds_gold: str = field(default_factory=lambda: _env("DATASET_GOLD", "crypto_gold"))
    ds_ops: str = field(default_factory=lambda: _env("DATASET_OPS", "crypto_ops"))
    dbt_project_dir: str = field(default_factory=lambda: _env("DBT_PROJECT_DIR", "/home/airflow/gcs/data/dbt/cryptowatch"))
    dbt_target: str = field(default_factory=lambda: _env("DBT_TARGET", "prod"))
    coingecko_base_url: str = field(default_factory=lambda: _env("COINGECKO_BASE_URL", "https://api.coingecko.com/api/v3"))
    coingecko_key_secret: str = field(default_factory=lambda: _env("COINGECKO_KEY_SECRET", "coingecko-demo-key"))
    slack_secret: str = field(default_factory=lambda: _env("SLACK_WEBHOOK_SECRET", "slack-webhook-url"))
    smtp_secret: str = field(default_factory=lambda: _env("SMTP_SECRET", "smtp-config"))
    anthropic_secret: str = field(default_factory=lambda: _env("ANTHROPIC_SECRET", "anthropic-api-key"))
    ai_model: str = field(default_factory=lambda: _env("AI_MODEL", "claude-sonnet-5-5"))
    channels: str = field(default_factory=lambda: _env("CHANNELS", "slack,email"))
    universe_size: int = field(default_factory=lambda: int(_env("UNIVERSE_SIZE", "500")))
    min_universe_rows: int = field(default_factory=lambda: int(_env("MIN_UNIVERSE_ROWS", "450")))
    max_slack_alerts: int = field(default_factory=lambda: int(_env("MAX_SLACK_ALERTS", "10")))
    max_explained: int = field(default_factory=lambda: int(_env("MAX_EXPLAINED", "10")))

    def raw_path(self, snapshot_date: str, name: str) -> str:
        return f"raw/snapshot_date={snapshot_date}/{name}.ndjson"


def settings() -> Settings:
    return Settings()
