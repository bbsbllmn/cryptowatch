"""CoinGecko extractor: HTTP client with retry/backoff and pure normalisers.

Design for a free Demo key (~30 calls/min, 10k/month): a daily run makes exactly 3 calls
(2 market pages of 250 + trending), spaced out, with Retry-After honoured. The normalisers are pure
functions over the documented JSON shape, so they are tested on recorded payloads with no network.
HTTP is injected (`http_get`) so tests never touch the internet.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class ExtractionError(RuntimeError):
    pass


class CoinGeckoClient:
    def __init__(self, base_url: str, api_key: str | None, http_get: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 5, min_interval: float = 2.5):
        if http_get is None:
            import requests
            http_get = requests.get
        self.base, self.key, self._get, self._sleep = base_url.rstrip("/"), api_key, http_get, sleep
        self.max_retries, self.min_interval, self._last = max_retries, min_interval, 0.0

    def get(self, path: str, params: dict | None = None):
        headers = {"accept": "application/json"}
        if self.key:
            headers["x-cg-demo-api-key"] = self.key       # header, never the query string (URLs get logged)
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                r = self._get(f"{self.base}{path}", params=params or {}, headers=headers, timeout=30)
            except Exception as exc:                          # network error: retry
                err = f"{type(exc).__name__}"
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code not in RETRY_STATUS:
                    raise ExtractionError(f"{path}: HTTP {r.status_code}")   # 401/403/404: retrying cannot help
                err = f"HTTP {r.status_code}"
                retry_after = r.headers.get("Retry-After") if getattr(r, "headers", None) else None
                if retry_after and retry_after.isdigit():
                    self._sleep(min(int(retry_after), 120))
            if attempt == self.max_retries:
                raise ExtractionError(f"{path}: gave up after {attempt + 1} attempts ({err})")
            delay = min(2 ** attempt * 2, 60)
            log.warning("%s failed (%s); retry %d in %ss", path, err, attempt + 1, delay)
            self._sleep(delay)
        raise ExtractionError(path)                           # unreachable; keeps type checkers calm

    # ------------------------------------------------------------------ endpoints
    def markets(self, pages: int = 2, per_page: int = 250) -> list[dict]:
        out: list[dict] = []
        for page in range(1, pages + 1):
            data = self.get("/coins/markets", {
                "vs_currency": "usd", "order": "market_cap_desc", "per_page": per_page, "page": page,
                "sparkline": "false", "price_change_percentage": "1h,24h,7d"})
            if not isinstance(data, list):
                raise ExtractionError("coins/markets returned a non-list payload")
            out.extend(data)
        return out

    def trending(self) -> dict:
        data = self.get("/search/trending")
        if not isinstance(data, dict) or "coins" not in data:
            raise ExtractionError("search/trending payload has no 'coins'")
        return data


# ---------------------------------------------------------------------- normalisers
def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def normalise_markets(items: list[dict], snapshot_date: str, fetched_at: str) -> list[dict]:
    """API shape -> flat typed rows. Duplicates (pagination can shift ranks between pages) keep the first
    occurrence; unparseable items are skipped and counted by the quality gate, never silently coerced."""
    rows, seen = [], set()
    for it in items:
        cid = it.get("id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        pct24 = it.get("price_change_percentage_24h_in_currency")
        if pct24 is None:
            pct24 = it.get("price_change_percentage_24h")
        rows.append({
            "snapshot_date": snapshot_date, "fetched_at": fetched_at, "coin_id": cid,
            "symbol": (it.get("symbol") or "").upper(), "name": it.get("name"), "image": it.get("image"),
            "current_price": _num(it.get("current_price")), "market_cap": _num(it.get("market_cap")),
            "market_cap_rank": it.get("market_cap_rank"), "total_volume": _num(it.get("total_volume")),
            "high_24h": _num(it.get("high_24h")), "low_24h": _num(it.get("low_24h")),
            "price_change_pct_1h": _num(it.get("price_change_percentage_1h_in_currency")),
            "price_change_pct_24h": _num(pct24),
            "price_change_pct_7d": _num(it.get("price_change_percentage_7d_in_currency")),
            "circulating_supply": _num(it.get("circulating_supply")),
            "ath": _num(it.get("ath")), "ath_change_pct": _num(it.get("ath_change_percentage")),
            "ath_date": _ts(it.get("ath_date")), "atl": _num(it.get("atl")), "atl_date": _ts(it.get("atl_date")),
            "last_updated": _ts(it.get("last_updated")),
        })
    return rows


def normalise_trending(payload: dict, snapshot_date: str, fetched_at: str) -> list[dict]:
    rows, seen = [], set()
    for entry in payload.get("coins", []):
        it = entry.get("item") or {}
        cid = it.get("id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        rows.append({"snapshot_date": snapshot_date, "fetched_at": fetched_at, "coin_id": cid,
                     "symbol": (it.get("symbol") or "").upper(), "name": it.get("name"),
                     "thumb": it.get("thumb"), "trend_rank": it.get("score"),
                     "market_cap_rank": it.get("market_cap_rank")})
    return rows
