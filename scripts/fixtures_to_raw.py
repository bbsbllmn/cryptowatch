#!/usr/bin/env python3
"""Runs the REAL extractor normalisers + quality gate over API-shaped payloads and writes the raw layer
(NDJSON per snapshot_date), exactly as the Airflow extract task does. Used by the e2e script."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
from cryptowatch.coingecko import normalise_markets, normalise_trending  # noqa: E402
from cryptowatch.quality import check_markets, check_trending  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fixtures", required=True, type=Path)
ap.add_argument("--lake", required=True, type=Path)
a = ap.parse_args()
for d in sorted((a.fixtures / "api").iterdir()):
    ds = d.name
    fetched = f"{ds}T07:00:00+00:00"
    items = json.loads((d / "markets_page1.json").read_text()) + json.loads((d / "markets_page2.json").read_text())
    m = normalise_markets(items, ds, fetched)
    t = normalise_trending(json.loads((d / "trending.json").read_text()), ds, fetched)
    from datetime import datetime
    check_markets(m, 450, now=datetime.fromisoformat(fetched))
    check_trending(t)
    for name, rows in (("markets", m), ("trending", t)):
        p = a.lake / "raw" / f"snapshot_date={ds}"
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{name}.ndjson").write_text("\n".join(json.dumps(r) for r in rows))
print("raw layer written for", len(list((a.fixtures / "api").iterdir())), "days")
