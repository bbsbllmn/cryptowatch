"""Assembles the Digest from gold alert rows."""
from __future__ import annotations

from .explain import explain_top
from .formatters import Digest

ALERTS_SQL = """
select alert_id, snapshot_date, coin_id, symbol, name, image, coin_link, rule_code, direction, severity,
       priority_score, current_price, price_change_pct_24h, price_change_pct_7d, market_cap, market_cap_rank,
       total_volume, tier, move_threshold_pct, z_24h, ath_change_pct, trend_rank, last_updated, is_repeat
from `{project}.{gold}.fct_alerts` where snapshot_date = date('{ds}') order by priority_score desc, alert_id
"""
UNIVERSE_SQL = "select count(*) n from `{project}.{gold}.fct_coin_snapshots` where snapshot_date = date('{ds}')"


def build_digest(ds: str, rows: list[dict], coins_scanned: int, llm, max_explained: int) -> Digest:
    notifiable = [r for r in rows if not r["is_repeat"]]
    notifiable.sort(key=lambda r: (-r["priority_score"], r["alert_id"]))
    return Digest(ds=ds, alerts=notifiable, repeats=len(rows) - len(notifiable), coins_scanned=coins_scanned,
                  explanations=explain_top(llm, notifiable, max_explained))
