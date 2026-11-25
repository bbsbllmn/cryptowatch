#!/usr/bin/env python3
"""Renders the real Slack payload and email HTML from a DuckDB fct_alerts, using the production digest code
(templates for explanations unless --llm-text is given). For previews and for the e2e check."""
import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
from cryptowatch.digest import build_digest  # noqa: E402
from cryptowatch.formatters import email_html, slack_payload  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--ds", required=True)
ap.add_argument("--out", required=True, type=Path)
a = ap.parse_args()
con = duckdb.connect(a.db, read_only=True)
cur = con.execute("select * from fct_alerts where snapshot_date = ? order by priority_score desc", [a.ds])
cols = [c[0] for c in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]
for r in rows:
    r["last_updated"] = str(r["last_updated"])
scanned = con.execute("select count(*) from fct_coin_snapshots where snapshot_date = ?", [a.ds]).fetchone()[0]
d = build_digest(a.ds, rows, scanned, None, 10)
a.out.mkdir(parents=True, exist_ok=True)
(a.out / "slack_payload.json").write_text(json.dumps(slack_payload(d), indent=2))
(a.out / "email_digest.html").write_text(email_html(d))
print(f"{a.ds}: {len(d.alerts)} notifiable alerts, {d.repeats} repeats suppressed, {scanned} coins -> {a.out}")
