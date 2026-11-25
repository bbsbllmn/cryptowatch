#!/usr/bin/env python3
"""
Runs the dbt project WITHOUT a warehouse, on the normalised raw layer.

Why: BigQuery isn't available in CI or on a laptop, but "the SQL looks right" is not evidence.
This harness proves the models build in dependency order and that every dbt test (generic and
singular) passes on real data, by rendering each model's Jinja, transpiling BigQuery SQL to DuckDB
(sqlglot) and executing it. It is a logic check, not a BigQuery-semantics check: partition
pruning, MERGE and insert_overwrite behaviour are NOT exercised (is_incremental() is False here),
so a real `dbt build` against a dev project remains a release gate.

  CW_PROJECT=t CW_DBT_TARGET=prod DBT_PROFILES_DIR=dbt/cryptowatch \
      dbt parse --project-dir dbt/cryptowatch        # produces target/manifest.json
  python scripts/offline_model_check.py --lake <lake dir> [--ds 2026-09-30]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import duckdb
import jinja2
import sqlglot
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "dbt" / "cryptowatch"


def load_sources(con, lake: Path) -> None:
    for name, table in (("markets", "src_raw_markets"), ("trending", "src_raw_trending")):
        files = sorted(glob.glob(str(lake / "raw" / "*" / f"{name}.ndjson")))
        if not files:
            raise SystemExit(f"no raw {name} files under {lake}")
        con.execute(f"create or replace table {table} as select * from read_json({files!r}, format='newline_delimited', "
                    f"union_by_name=true, timestamp_format='%Y-%m-%dT%H:%M:%S%z')")
        con.execute(f"alter table {table} alter snapshot_date type date")
        con.execute(f"alter table {table} alter fetched_at type timestamp with time zone")


def load_seeds(con) -> None:
    for csv in (PROJECT / "seeds").glob("*.csv"):
        con.execute(f"create or replace table {csv.stem} as select * from read_csv_auto('{csv}', header=true)")


def make_env(ds: str) -> tuple[jinja2.Environment, dict]:
    proj_vars = yaml.safe_load((PROJECT / "dbt_project.yml").read_text()).get("vars", {})
    proj_vars["ds"] = ds
    env = jinja2.Environment(extensions=["jinja2.ext.do"], undefined=jinja2.StrictUndefined)
    ctx = {
        "ref": lambda name, *a: name,
        "source": lambda s, t: f"src_{t}",
        "var": lambda k, d=None: proj_vars.get(k, d),
        "config": lambda **kw: "",
        "is_incremental": lambda: False,
        "return": lambda v: str(v),            # only used by recent_partitions(), which feeds config()
        "target": type("T", (), {"name": "prod", "schema": "crypto_gold"})(),
    }
    macros = "\n".join(p.read_text() for p in (PROJECT / "macros").glob("*.sql"))
    # generic tests are handled in Python below, so only load non-test macros
    macros = re.sub(r"{%\s*test .*?{%\s*endtest\s*%}", "", macros, flags=re.S)
    macros = re.sub(r"{%-?\s*macro generate_schema_name.*?endmacro\s*%}", "", macros, flags=re.S)
    return env, {"macros": macros, **ctx}


def render(env, base: dict, raw: str) -> str:
    tpl = env.from_string(base["macros"] + "\n" + raw)
    ctx = {k: v for k, v in base.items() if k != "macros"}
    # macros call each other and use `var`; expose the context as template globals
    tpl.globals.update(ctx)
    return tpl.render(**ctx)


def to_duck(sql: str) -> str:
    return ";\n".join(sqlglot.transpile(sql, read="bigquery", write="duckdb"))


def generic_test_sql(tm: dict, model: str, col: str | None) -> str:
    n, kw = tm["name"], tm.get("kwargs", {})
    if n == "not_null":
        return f"select * from {model} where {col} is null"
    if n == "unique":
        return f"select {col} from {model} where {col} is not null group by {col} having count(*) > 1"
    if n == "accepted_values":
        vals = kw["values"]
        lit = ", ".join(str(v) if kw.get("quote") is False else "'" + str(v) + "'" for v in vals)
        return f"select * from {model} where {col} is not null and {col} not in ({lit})"
    if n == "relationships":
        to = re.search(r"ref\('([^']+)'\)", str(kw["to"])).group(1)
        return (f"select c.{col} from {model} c left join {to} p on c.{col} = p.{kw['field']} "
                f"where c.{col} is not null and p.{kw['field']} is null")
    if n == "expression_is_true":
        w = f" and ({kw['where']})" if kw.get("where") else ""
        return f"select * from {model} where not ({kw['expression']}){w}"
    if n == "dbt_utils_free_unique_key":
        return f"select coin_id, snapshot_date from {model} group by 1, 2 having count(*) > 1"
    if n == "not_negative":
        return f"select * from {model} where {col} < 0"
    raise SystemExit(f"harness does not implement generic test {n!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", required=True, type=Path)
    ap.add_argument("--ds", default="2026-11-10")
    ap.add_argument("--manifest", type=Path, default=PROJECT / "target" / "manifest.json")
    ap.add_argument("--keep-db", type=Path, help="write the DuckDB file here for inspection")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    con = duckdb.connect(str(args.keep_db) if args.keep_db else ":memory:")
    load_sources(con, args.lake)
    load_seeds(con)
    env, base = make_env(args.ds)

    nodes = manifest["nodes"]
    models = {k: v for k, v in nodes.items() if v["resource_type"] == "model"}
    order, seen = [], set()

    def visit(uid):
        if uid in seen or uid not in models:
            return
        seen.add(uid)
        for d in models[uid]["depends_on"]["nodes"]:
            visit(d)
        order.append(uid)

    for uid in models:
        visit(uid)

    failures = 0
    print(f"== building {len(order)} models (ds={args.ds}) ==")
    for uid in order:
        m = models[uid]
        try:
            sql = to_duck(render(env, base, m["raw_code"]))
            con.execute(f'create or replace table {m["name"]} as {sql}')
            n = con.execute(f'select count(*) from {m["name"]}').fetchone()[0]
            print(f"  ok   {m['name']:<32} {n:>9,} rows")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  FAIL {m['name']}: {str(e).splitlines()[0][:300]}")

    tests = {k: v for k, v in nodes.items() if v["resource_type"] == "test"}
    print(f"== running {len(tests)} tests ==")
    passed = 0
    for uid, t in sorted(tests.items(), key=lambda kv: kv[1]["name"]):
        try:
            if "test_metadata" in t:
                dep = t["depends_on"]["nodes"][0] if t["depends_on"]["nodes"] else ""
                tgt = nodes.get(t.get("attached_node") or dep, {}).get("name")
                if tgt is None:                      # a test on a source table
                    tgt = "src_" + manifest["sources"][dep]["name"]
                sql = generic_test_sql(t["test_metadata"], tgt, t.get("column_name"))
            else:
                sql = to_duck(render(env, base, t["raw_code"]))
            bad = con.execute(f"select count(*) from ({sql}) q").fetchone()[0]
            if bad:
                failures += 1
                print(f"  FAIL {t['name'][:90]}  ({bad:,} offending rows)")
            else:
                passed += 1
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  ERROR {t['name'][:90]}: {str(e).splitlines()[0][:200]}")
    print(f"== {passed}/{len(tests)} tests passed, {failures} failure(s) ==")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
