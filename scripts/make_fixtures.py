#!/usr/bin/env python3
"""Synthetic CoinGecko-shaped API responses + ground truth, so the whole pipeline is testable offline.

Shapes follow the documented /coins/markets and /search/trending responses (field names, nullability).
Random walks are CLIPPED well below each tier's threshold so only the injected events can alert; truth.json
lists exactly which alerts must exist, and which must not be notified, which makes the check exact.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

TIERS = [  # (min_cap, threshold_pct, sigma, clip)  mirrors dbt seeds/alert_thresholds.csv
    (10e9, 20, 2.0, 8), (1e9, 35, 4.0, 14), (1e8, 50, 6.0, 20), (0, 85, 12.0, 35)]


def tier_of(cap):
    return next(t for t in TIERS if cap >= t[0])


def build(out: Path, start: str = "2026-11-01", days: int = 10, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    d0 = date.fromisoformat(start)
    base = [{"id": f"coin-{i:03d}", "name": f"Coin {i:03d}", "symbol": f"c{i:03d}",
             "cap": 1.5e12 * i ** -1.6, "price": float(10 ** rng.uniform(-4, 4)), "n": 1000 + i}
            for i in range(1, 501)]
    by_id = {c["id"]: c for c in base}
    drop_coin = "coin-500"                                  # coin-500 leaves on day 7 and coin-499 on day 5, keeping the universe at 500
    new_hi = {"id": "newcoin-1", "name": "Fresh Token", "symbol": "frsh", "cap": 2.5e8, "price": 0.42, "n": 9001}
    new_med = {"id": "returner-1", "name": "Returner", "symbol": "rtn", "cap": 1.1e8, "price": 1.3, "n": 9002}
    E = {"pump": "coin-480", "illiquid": "coin-470", "dump": "coin-003", "small": "coin-230",
         "trend_new": "coin-120", "trend_warm": "coin-090"}
    steady_trending = [f"coin-{i:03d}" for i in range(1, 15)]  # same 14 every day -> never "new"
    day = lambda n: (d0 + timedelta(days=n - 1)).isoformat()  # noqa: E731
    truth = {"alerts": [], "not_alerted": [], "baseline": day(1), "start": start, "days": days}

    for n in range(1, days + 1):
        ds = day(n)
        universe = [c for c in base if not ((c["id"] == drop_coin and n >= 7) or (c["id"] == "coin-499" and n >= 5))]
        if n >= 5:
            universe.append(new_hi)
        if n >= 7:
            universe.append(new_med)
        universe.sort(key=lambda c: -c["cap"])
        events = {}
        if n == 6:
            events[E["small"]] = 55.0
        if n == 8:
            events[E["pump"]] = 120.0
            events[E["illiquid"]] = 150.0
        if n == 9:
            events[E["dump"]] = -25.0
            events[E["pump"]] = 100.0
        items = []
        for rank, c in enumerate(universe, 1):
            cap = c["cap"]
            _, thr, sigma, clip = tier_of(cap)
            chg = float(np.clip(rng.normal(0, sigma), -clip, clip))
            vol = cap * float(rng.uniform(0.03, 0.2))
            chg = events.get(c["id"], chg)
            if c["id"] == E["illiquid"] and n == 8:
                vol = 20_000.0
            atl = (datetime.fromisoformat(ds) - timedelta(days=2 if c["id"] == "newcoin-1" else 900)).replace(tzinfo=timezone.utc)
            items.append({
                "id": c["id"], "symbol": c["symbol"], "name": c["name"],
                "image": f"https://coin-images.coingecko.com/coins/images/{c['n']}/large/{c['id']}.png",
                "current_price": c["price"] * (1 + chg / 100), "market_cap": cap, "market_cap_rank": rank,
                "fully_diluted_valuation": None, "total_volume": vol, "high_24h": c["price"] * 1.02,
                "low_24h": c["price"] * 0.98, "price_change_24h": c["price"] * chg / 100,
                "price_change_percentage_24h": chg, "market_cap_change_24h": None,
                "market_cap_change_percentage_24h": None, "circulating_supply": cap / c["price"],
                "total_supply": None, "max_supply": None, "ath": c["price"] * 3, "ath_change_percentage": -66.0,
                "ath_date": "2024-03-14T00:00:00.000Z", "atl": c["price"] * 0.1, "atl_change_percentage": 900.0,
                "atl_date": atl.isoformat().replace("+00:00", "Z"), "roi": None,
                "last_updated": f"{ds}T05:{rng.integers(0, 59):02d}:00.000Z",
                "price_change_percentage_1h_in_currency": float(rng.normal(0, 0.5)),
                "price_change_percentage_24h_in_currency": chg,
                "price_change_percentage_7d_in_currency": float(rng.normal(0, sigma * 2))})
        trend_ids = list(steady_trending)
        if n >= 2:
            trend_ids[-1] = E["trend_warm"]                 # new on day 2: inside warm-up -> no alert
        if n >= 6:
            trend_ids[-2] = E["trend_new"]                  # new on day 6 -> alert; stays on day 7 -> not new
        trending = {"coins": [{"item": {
            "id": cid, "coin_id": i, "name": by_id.get(cid, {"name": cid})["name"], "symbol": cid.upper(),
            "market_cap_rank": 1, "thumb": f"https://coin-images.coingecko.com/coins/images/{i}/thumb/x.png",
            "small": "", "large": "", "slug": cid, "price_btc": 0.0, "score": i,
            "data": {"price": 1.0}}} for i, cid in enumerate(trend_ids)], "nfts": [], "categories": []}
        d = out / "api" / ds
        d.mkdir(parents=True, exist_ok=True)
        (d / "markets_page1.json").write_text(json.dumps(items[:250]))
        (d / "markets_page2.json").write_text(json.dumps(items[250:]))
        (d / "trending.json").write_text(json.dumps(trending))

    A = truth["alerts"]
    A += [dict(date=day(6), coin=E["small"], rule="PRICE_MOVE", notified=True),
          dict(date=day(8), coin=E["pump"], rule="PRICE_MOVE", notified=True),
          dict(date=day(9), coin=E["dump"], rule="PRICE_MOVE", notified=True),
          dict(date=day(9), coin=E["pump"], rule="PRICE_MOVE", notified=False),     # repeat within 3 days
          dict(date=day(6), coin=E["trend_new"], rule="NEWLY_TRENDING", notified=True),
          dict(date=day(5), coin="newcoin-1", rule="NEW_IN_UNIVERSE", notified=True),
          dict(date=day(7), coin="returner-1", rule="NEW_IN_UNIVERSE", notified=True)]
    truth["not_alerted"] = [dict(date=day(8), coin=E["illiquid"], why="below the 24h volume floor"),
                            dict(date=day(2), coin=E["trend_warm"], why="trending warm-up period")]
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--start", default="2026-11-01")
    ap.add_argument("--days", type=int, default=10)
    a = ap.parse_args()
    t = build(a.out, a.start, a.days)
    print(f"wrote {a.days} days of API payloads, {len(t['alerts'])} expected alerts -> {a.out}")
