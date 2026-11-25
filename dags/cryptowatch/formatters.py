"""Message formatting. Everything from the API (names, symbols, URLs) is untrusted: escaped for the target
format, and links/images must be https."""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from .grounding import clean_name

SEV_ICON = {"HIGH": ":rotating_light:", "MEDIUM": ":warning:", "LOW": ":information_source:"}
RULE_LABEL = {"PRICE_MOVE": "Price move", "NEWLY_TRENDING": "Newly trending", "NEW_IN_UNIVERSE": "New in top 500"}


@dataclass
class Digest:
    ds: str
    alerts: list[dict]                       # notifiable alerts (not repeats), highest priority first
    repeats: int = 0
    coins_scanned: int = 0
    explanations: dict = field(default_factory=dict)   # alert_id -> {"text", "source"}

    @property
    def high(self) -> int:
        return sum(1 for a in self.alerts if a["severity"] == "HIGH")

    @property
    def subject(self) -> str:
        if not self.alerts:
            return f"Crypto digest {self.ds}: all quiet"
        return f"Crypto digest {self.ds}: {len(self.alerts)} alert{'s' if len(self.alerts) != 1 else ''} ({self.high} high)"


def safe_https(url: str | None) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") and " " not in url and len(url) < 500 else None


def fmt_price(p: float | None) -> str:
    if p is None:
        return "n/a"
    if abs(p) >= 1:
        return f"${p:,.2f}"
    import math
    return f"${p:.{min(12, 3 - math.floor(math.log10(abs(p))))}f}" if p else "$0"   # 4 significant digits


def fmt_cap(c: float | None) -> str:
    if c is None:
        return "n/a"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(c) >= div:
            return f"${c / div:.2f}{suf}"
    return f"${c:,.0f}"


def fmt_pct(p: float | None) -> str:
    return "n/a" if p is None else f"{p:+.2f}%"


def fmt_ts(ts) -> str:
    if ts is None:
        return "n/a"
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def slack_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _title(a: dict) -> str:
    return f"{clean_name(a.get('name'))} ({clean_name(a.get('symbol'), 12).upper()})"


def slack_payload(d: Digest, max_alerts: int = 10) -> dict:
    head = f"Crypto digest {d.ds}"
    if not d.alerts:
        return {"text": d.subject, "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": head}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f":white_check_mark: All quiet: {d.coins_scanned} coins scanned, no new alerts"
                     + (f" ({d.repeats} continuing)." if d.repeats else ".")}}]}
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": head}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text":
               f"*{len(d.alerts)}* alert{'s' if len(d.alerts) != 1 else ''} ({d.high} high) from {d.coins_scanned} coins"
               + (f" · {d.repeats} continuing, not repeated" if d.repeats else "")}]}]
    for a in d.alerts[:max_alerts]:
        link = safe_https(a.get("coin_link"))
        title = slack_escape(_title(a))
        title = f"<{link}|{title}>" if link else title
        lines = [f"{SEV_ICON.get(a['severity'], '')} *{title}* · {RULE_LABEL.get(a['rule_code'], a['rule_code'])}",
                 f"*Price* {fmt_price(a.get('current_price'))} · *24h* {fmt_pct(a.get('price_change_pct_24h'))} · "
                 f"*Mkt cap* {fmt_cap(a.get('market_cap'))} (#{a.get('market_cap_rank') or '?'})",
                 f"_{fmt_ts(a.get('last_updated'))}_"]
        ex = d.explanations.get(a["alert_id"])
        if ex:
            lines.append(slack_escape(ex["text"]))
        section = {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]}}
        img = safe_https(a.get("image"))
        if img:
            section["accessory"] = {"type": "image", "image_url": img, "alt_text": slack_escape(_title(a))}
        blocks += [section, {"type": "divider"}]
    if len(d.alerts) > max_alerts:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": f"+{len(d.alerts) - max_alerts} more alerts: see the email digest."}]})
    return {"text": d.subject, "blocks": blocks[:50]}


def email_html(d: Digest) -> str:
    e = html.escape
    rows = []
    for a in d.alerts:
        link, img = safe_https(a.get("coin_link")), safe_https(a.get("image"))
        name = e(_title(a))
        name = f'<a href="{e(link)}">{name}</a>' if link else name
        logo = f'<img src="{e(img)}" width="28" height="28" alt=""> ' if img else ""
        ex = d.explanations.get(a["alert_id"])
        color = "#b00020" if (a.get("price_change_pct_24h") or 0) < 0 else "#0a7d32"
        rows.append(
            f"<tr><td>{logo}{name}</td><td>{e(RULE_LABEL.get(a['rule_code'], a['rule_code']))}<br><small>{e(a['severity'])}</small></td>"
            f"<td align=right>{e(fmt_price(a.get('current_price')))}</td>"
            f'<td align=right style="color:{color}">{e(fmt_pct(a.get("price_change_pct_24h")))}</td>'
            f"<td align=right>{e(fmt_cap(a.get('market_cap')))}</td><td>{e(fmt_ts(a.get('last_updated')))}</td></tr>"
            + (f'<tr><td colspan=6><small>{e(ex["text"])}</small></td></tr>' if ex else ""))
    body = ("<p>All quiet: no new alerts today.</p>" if not rows else
            '<table cellpadding=6 cellspacing=0 border=1 style="border-collapse:collapse;font-family:sans-serif">'
            "<tr><th>Coin</th><th>Rule</th><th>Price</th><th>24h</th><th>Market cap</th><th>Updated</th></tr>"
            + "".join(rows) + "</table>")
    return (f"<html><body><h2>{e(d.subject)}</h2><p>{d.coins_scanned} coins scanned"
            f"{f', {d.repeats} continuing (not repeated)' if d.repeats else ''}.</p>{body}"
            "<p><small>Monitoring data from CoinGecko; not financial advice.</small></p></body></html>")


def email_text(d: Digest) -> str:
    lines = [d.subject, ""]
    for a in d.alerts:
        lines.append(f"- {_title(a)} [{a['severity']}] {RULE_LABEL.get(a['rule_code'], a['rule_code'])}: "
                     f"{fmt_price(a.get('current_price'))}, 24h {fmt_pct(a.get('price_change_pct_24h'))}, "
                     f"cap {fmt_cap(a.get('market_cap'))}, {fmt_ts(a.get('last_updated'))} {a.get('coin_link') or ''}")
    return "\n".join(lines) if d.alerts else d.subject + "\nNo new alerts."
