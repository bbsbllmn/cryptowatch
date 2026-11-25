#!/usr/bin/env bash
# End-to-end proof with no cloud and no network:
#   fixtures (CoinGecko-shaped) -> real extractor normalisers + quality gate -> raw layer
#   -> dbt models + tests (DuckDB) -> exact comparison with ground truth -> rendered Slack/email previews
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; W="${1:-$(mktemp -d)}"
python "$ROOT/scripts/make_fixtures.py" --out "$W/fx"
python "$ROOT/scripts/fixtures_to_raw.py" --fixtures "$W/fx" --lake "$W/lake"
( cd "$ROOT/dbt/cryptowatch" && CW_PROJECT=e2e CW_DBT_TARGET=prod DBT_PROFILES_DIR=$PWD dbt parse >/dev/null )
python "$ROOT/scripts/offline_model_check.py" --lake "$W/lake" --keep-db "$W/cw.duckdb"
python "$ROOT/scripts/check_alerts_against_truth.py" --db "$W/cw.duckdb" --truth "$W/fx/truth.json"
python "$ROOT/scripts/render_sample_digest.py" --db "$W/cw.duckdb" --ds 2026-11-08 --out "$W/preview"
echo "previews in $W/preview"
