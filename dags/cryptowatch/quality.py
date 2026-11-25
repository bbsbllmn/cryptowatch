"""Pre-load data contract for a snapshot. A bad snapshot must stop the pipeline BEFORE it can generate
alerts: a half-empty API response would otherwise look like 'every coin vanished / re-appeared as new'."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class DataContractError(ValueError):
    """Permanent data problem: retrying the same response cannot fix it."""


def check_markets(rows: list[dict], min_rows: int, now: datetime | None = None, max_age_hours: int = 12) -> dict:
    now = now or datetime.now(timezone.utc)
    problems = []
    if len(rows) < min_rows:
        problems.append(f"only {len(rows)} coins (need >= {min_rows})")
    ids = [r["coin_id"] for r in rows]
    if len(ids) != len(set(ids)):
        problems.append("duplicate coin ids")
    null_price = sum(1 for r in rows if r["current_price"] is None or r["current_price"] <= 0)
    if rows and null_price / len(rows) > 0.02:
        problems.append(f"{null_price} coins with missing/non-positive price (>2%)")
    null_chg = sum(1 for r in rows if r["price_change_pct_24h"] is None)
    if rows and null_chg / len(rows) > 0.10:
        problems.append(f"{null_chg} coins without a 24h change (>10%)")
    stamps = [datetime.fromisoformat(r["last_updated"]) for r in rows if r.get("last_updated")]
    if stamps and now - max(stamps) > timedelta(hours=max_age_hours):
        problems.append(f"newest price is {now - max(stamps)} old: upstream is stale")
    if problems:
        raise DataContractError("; ".join(problems))
    return {"rows": len(rows), "null_price": null_price, "null_change": null_chg}


def check_trending(rows: list[dict]) -> dict:
    if not rows:
        raise DataContractError("trending list is empty")
    return {"rows": len(rows)}
