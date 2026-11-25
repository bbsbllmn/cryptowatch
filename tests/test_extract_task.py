import pytest

from cryptowatch.coingecko import CoinGeckoClient
from cryptowatch.quality import DataContractError
from cryptowatch.tasks import MemoryStore, extract
from datetime import datetime, timezone

NOW = datetime(2026, 11, 10, 7, tzinfo=timezone.utc)


class Resp:
    status_code = 200
    def __init__(self, b): self._b = b
    def json(self): return self._b


def api(n_calls):
    def get(url, params, headers, timeout):
        n_calls.append(url)
        if url.endswith("/coins/markets"):
            base = (params["page"] - 1) * 250
            return Resp([{"id": f"c{base + i}", "symbol": "x", "name": "X", "current_price": 1.0, "market_cap": 1e9,
                          "price_change_percentage_24h": 0.5, "last_updated": "2026-11-10T05:00:00.000Z"} for i in range(250)])
        return Resp({"coins": [{"item": {"id": "bonk", "symbol": "b", "name": "B", "score": 0}}]})
    return CoinGeckoClient("https://api", "k", get, sleep=lambda s: None)


def test_extract_lands_validates_and_a_retry_reuses_without_calling_the_api():
    calls, store = [], MemoryStore()
    r = extract("markets", "2026-11-10", "2026-11-10", api(calls), store, "raw/m.ndjson", now=NOW)
    assert r["reused"] is False and r["rows"] == 500 and len(calls) == 2
    again = extract("markets", "2026-11-10", "2026-11-10", api(calls), store, "raw/m.ndjson", now=NOW)
    assert again["reused"] is True and len(calls) == 2            # quota not burned by the retry


def test_past_day_without_a_landed_snapshot_is_refused_not_faked():
    with pytest.raises(DataContractError, match="past day"):
        extract("markets", "2026-11-09", "2026-11-10", api([]), MemoryStore(), "k", now=NOW)


def test_past_day_with_landed_snapshot_can_be_reprocessed():
    s = MemoryStore()
    s.write("k", '{"coin_id":"a"}\n{"coin_id":"b"}')
    assert extract("markets", "2026-11-09", "2026-11-10", None, s, "k")["rows"] == 2


def test_bad_snapshot_is_not_landed():
    store = MemoryStore()
    with pytest.raises(DataContractError, match="only"):
        extract("markets", "2026-11-10", "2026-11-10", api([]), store, "k", min_rows=900, now=NOW)
    assert not store.exists("k")                                   # a rejected snapshot never reaches the lake


def test_trending_extract():
    r = extract("trending", "2026-11-10", "2026-11-10", api([]), MemoryStore(), "t", now=NOW)
    assert r["rows"] == 1
