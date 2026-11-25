"""Testable task logic (storage and HTTP injected). The DAG file only wires these to Airflow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol

from .coingecko import CoinGeckoClient, normalise_markets, normalise_trending
from .quality import DataContractError, check_markets, check_trending

MARKETS_SCHEMA = [
    ("snapshot_date", "DATE"), ("fetched_at", "TIMESTAMP"), ("coin_id", "STRING"), ("symbol", "STRING"),
    ("name", "STRING"), ("image", "STRING"), ("current_price", "FLOAT64"), ("market_cap", "FLOAT64"),
    ("market_cap_rank", "INT64"), ("total_volume", "FLOAT64"), ("high_24h", "FLOAT64"), ("low_24h", "FLOAT64"),
    ("price_change_pct_1h", "FLOAT64"), ("price_change_pct_24h", "FLOAT64"), ("price_change_pct_7d", "FLOAT64"),
    ("circulating_supply", "FLOAT64"), ("ath", "FLOAT64"), ("ath_change_pct", "FLOAT64"), ("ath_date", "TIMESTAMP"),
    ("atl", "FLOAT64"), ("atl_date", "TIMESTAMP"), ("last_updated", "TIMESTAMP")]
TRENDING_SCHEMA = [
    ("snapshot_date", "DATE"), ("fetched_at", "TIMESTAMP"), ("coin_id", "STRING"), ("symbol", "STRING"),
    ("name", "STRING"), ("thumb", "STRING"), ("trend_rank", "INT64"), ("market_cap_rank", "INT64")]


def bq_schema(fields):
    return [{"name": n, "type": t, "mode": "NULLABLE"} for n, t in fields]


class ObjectStore(Protocol):
    def exists(self, key: str) -> bool: ...
    def read(self, key: str) -> str: ...
    def write(self, key: str, text: str) -> None: ...


class MemoryStore:
    def __init__(self):
        self.objs = {}

    def exists(self, key): return key in self.objs
    def read(self, key): return self.objs[key]
    def write(self, key, text): self.objs[key] = text


def to_ndjson(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r, separators=(",", ":")) for r in rows)


def extract(kind: str, ds: str, today: str, client: CoinGeckoClient | None, store: ObjectStore,
            key: str, min_rows: int = 450, now: datetime | None = None) -> dict:
    """Idempotent extract of one dataset for one snapshot date.

    * If the raw object already exists (retry / re-run), it is reused: zero API calls, so retries never burn
      the free-tier quota and a re-run reproduces the same alerts.
    * CoinGecko serves 'now' only, so a missing snapshot for a past date cannot be reconstructed; refuse
      rather than quietly stamping today's prices with an old date.
    """
    if store.exists(key):
        return {"reused": True, "key": key, "rows": len(store.read(key).splitlines())}
    if ds != today:
        raise DataContractError(f"no landed {kind} snapshot for {ds} and the free API only serves current data "
                                f"(today is {today}); a past day cannot be re-fetched")
    now = now or datetime.now(timezone.utc)
    fetched = now.isoformat()
    if kind == "markets":
        rows = normalise_markets(client.markets(pages=2, per_page=250), ds, fetched)
        stats = check_markets(rows, min_rows, now)
    else:
        rows = normalise_trending(client.trending(), ds, fetched)
        stats = check_trending(rows)
    store.write(key, to_ndjson(rows))
    return {"reused": False, "key": key, **stats}
