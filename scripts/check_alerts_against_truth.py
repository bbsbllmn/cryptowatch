#!/usr/bin/env python3
"""Exact comparison of fct_alerts with the fixture generator's ground truth (set equality, not 'looks right')."""
import argparse
import json
import sys

import duckdb

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--truth", required=True)
a = ap.parse_args()
truth = json.load(open(a.truth))
rows = duckdb.connect(a.db, read_only=True).execute(
    "select cast(snapshot_date as varchar), coin_id, rule_code, is_repeat, severity from fct_alerts").fetchall()
got = {(d, c, r): (not rep) for d, c, r, rep, _ in rows}
want = {(x["date"], x["coin"], x["rule"]): x["notified"] for x in truth["alerts"]}
missing, extra = sorted(set(want) - set(got)), sorted(set(got) - set(want))
wrong_notify = sorted(k for k in want if k in got and want[k] != got[k])
forbidden = [(x["date"], x["coin"]) for x in truth["not_alerted"] if any(d == x["date"] and c == x["coin"] for d, c, _ in got)]
print(f"expected {len(want)} alerts, got {len(got)}; missing={missing} extra={extra} "
      f"wrong_notify_flag={wrong_notify} forbidden_present={forbidden}")
sys.exit(1 if (missing or extra or wrong_notify or forbidden) else 0)
