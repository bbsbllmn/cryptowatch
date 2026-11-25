from datetime import datetime, timezone

import pytest

from cryptowatch.coingecko import CoinGeckoClient, ExtractionError, normalise_markets, normalise_trending
from cryptowatch.quality import DataContractError, check_markets, check_trending


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._b, self.headers = status, body, headers or {}

    def json(self):
        return self._b


def client(responses, **kw):
    calls, sleeps = [], []

    def http_get(url, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers})
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    c = CoinGeckoClient("https://api.example/v3/", "KEY", http_get, sleep=sleeps.append, **kw)
    return c, calls, sleeps


def test_key_goes_in_header_not_url_and_pages_are_requested():
    c, calls, _ = client([Resp(200, [{"id": "a"}]), Resp(200, [{"id": "b"}])])
    assert [x["id"] for x in c.markets(pages=2)] == ["a", "b"]
    assert all(x["headers"]["x-cg-demo-api-key"] == "KEY" and "KEY" not in str(x["params"]) for x in calls)
    assert [x["params"]["page"] for x in calls] == [1, 2] and calls[0]["params"]["price_change_percentage"] == "1h,24h,7d"


def test_retries_on_429_honouring_retry_after_then_succeeds():
    c, calls, sleeps = client([Resp(429, headers={"Retry-After": "7"}), Resp(200, [])])
    assert c.markets(pages=1) == []
    assert 7 in sleeps and len(calls) == 2


def test_retries_network_errors_then_gives_up():
    c, calls, _ = client([ConnectionError("x")] * 3, max_retries=2)
    with pytest.raises(ExtractionError, match="gave up after 3"):
        c.markets(pages=1)
    assert len(calls) == 3


@pytest.mark.parametrize("status", [401, 403, 404])
def test_client_errors_are_not_retried(status):
    c, calls, _ = client([Resp(status)])
    with pytest.raises(ExtractionError, match=str(status)):
        c.markets(pages=1)
    assert len(calls) == 1


def test_trending_payload_shape_is_checked():
    c, *_ = client([Resp(200, {"unexpected": 1})])
    with pytest.raises(ExtractionError):
        c.trending()


ITEM = {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "image": "https://x/y.png", "current_price": 77671,
        "market_cap": 1.5e12, "market_cap_rank": 1, "total_volume": 3.3e10, "price_change_percentage_24h": -0.95,
        "price_change_percentage_24h_in_currency": -0.953, "ath_date": "2025-10-06T18:57:42.558Z",
        "atl_date": None, "last_updated": "2026-05-18T12:49:21.599Z", "roi": None}


def test_normalise_markets_prefers_in_currency_change_and_parses_dates():
    r = normalise_markets([ITEM, ITEM, {"symbol": "no-id"}], "2026-05-18", "t")[0]
    assert r["price_change_pct_24h"] == -0.953 and r["symbol"] == "BTC" and r["atl_date"] is None
    assert r["ath_date"].startswith("2025-10-06T18:57:42") and r["current_price"] == 77671.0
    assert len(normalise_markets([ITEM, ITEM, {"symbol": "no-id"}], "d", "t")) == 1      # duplicate + id-less dropped


def test_normalise_markets_falls_back_to_plain_24h_and_tolerates_nulls():
    r = normalise_markets([{**ITEM, "price_change_percentage_24h_in_currency": None, "current_price": None,
                            "market_cap": "oops"}], "d", "t")[0]
    assert r["price_change_pct_24h"] == -0.95 and r["current_price"] is None and r["market_cap"] is None


def test_normalise_trending():
    p = {"coins": [{"item": {"id": "bonk", "symbol": "BONK", "name": "Bonk", "thumb": "https://t", "score": 0,
                             "market_cap_rank": 103}}, {"item": {}}]}
    assert normalise_trending(p, "d", "t") == [{"snapshot_date": "d", "fetched_at": "t", "coin_id": "bonk",
                                               "symbol": "BONK", "name": "Bonk", "thumb": "https://t",
                                               "trend_rank": 0, "market_cap_rank": 103}]


def _rows(n, **over):
    now = datetime(2026, 5, 18, 13, tzinfo=timezone.utc)
    return [{"coin_id": f"c{i}", "current_price": 1.0, "price_change_pct_24h": 0.1,
             "last_updated": now.isoformat(), **over} for i in range(n)], now


def test_gate_accepts_a_healthy_snapshot():
    rows, now = _rows(500)
    assert check_markets(rows, 450, now)["rows"] == 500


@pytest.mark.parametrize("mutate,msg", [
    (lambda r: r[:100], "only 100"),
    (lambda r: r + [r[0]], "duplicate"),
    (lambda r: [{**x, "current_price": None} for x in r[:20]] + r[20:], "missing/non-positive price"),
    (lambda r: [{**x, "price_change_pct_24h": None} for x in r[:80]] + r[80:], "without a 24h change"),
])
def test_gate_rejects_bad_snapshots(mutate, msg):
    rows, now = _rows(500)
    with pytest.raises(DataContractError, match=msg):
        check_markets(mutate(rows), 450, now)


def test_gate_rejects_stale_upstream():
    rows, now = _rows(500, last_updated="2026-05-17T00:00:00+00:00")
    with pytest.raises(DataContractError, match="stale"):
        check_markets(rows, 450, now)


def test_trending_gate():
    with pytest.raises(DataContractError):
        check_trending([])
