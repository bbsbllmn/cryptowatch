"""Output guardrails for LLM text. The model writes prose; this code decides if the prose may ship.

* numbers_grounded: every number in the text must equal a supplied fact rounded or truncated to the precision
  the text itself displays, so '$521.9M' matches 521,967,819 but '$900M' and '86%' (for 85.3) do not.
  Sign is ignored ('fell 85.3%' matches -85.3) and a % may match a ratio.
* no_advice / no_links: this is monitoring, not investment advice; and model text must never inject links.
"""
from __future__ import annotations

import re

# a number may be glued to letters ("104th") - it must still be checked, so only a following digit is excluded;
# a unit suffix counts only when not followed by another letter ("104th" is not 104 trillion).
_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(?:(bn|tn|t|b|m|k|%)(?![A-Za-z]))?(?!\d)", re.I)
_SCALE = {"tn": 1e12, "t": 1e12, "bn": 1e9, "b": 1e9, "m": 1e6, "k": 1e3}
_ADVICE = re.compile(r"\b(buy|sell|hold|invest\w*|should|recommend\w*|guarantee\w*|moon\w*|will (rise|fall|drop|surge|"
                     r"increase|decrease)|going to|financial advice|not financial)\b", re.I)
_LINK = re.compile(r"https?://|www\.|\]\(|<a\s", re.I)


def _numbers_in(text: str):
    for m in _NUM.finditer(text):
        whole, frac, suf = m.group(1).replace(",", ""), m.group(2) or "", (m.group(3) or "").lower()
        scale = _SCALE.get(suf, 1.0)
        yield float(whole + frac) * scale, suf == "%", scale * (10 ** -(len(frac) - 1 if frac else 0))


def _flatten(obj) -> list[float]:
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, (int, float)):
        return [abs(float(obj))]
    if isinstance(obj, str):
        return [abs(v) for v, _, _ in _numbers_in(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _flatten(v)]
    if isinstance(obj, (list, tuple)):
        return [n for v in obj for n in _flatten(v)]
    return []


def _matches(c: float, unit: float, f: float) -> bool:
    """c is f rounded OR truncated to the precision (`unit`) that the text itself displays."""
    import math
    q = f / unit
    return any(abs(c - r * unit) <= unit * 1e-6 + 1e-15 for r in (math.floor(q + 0.5), math.floor(q)))


# standard look-back windows are constants of the product, not facts to ground ("24h", "7d")
_WINDOW = re.compile(r"\b(1|7|14|24|30)\s?(h|hr|hrs|d|day|days|hour|hours)\b", re.I)


def ungrounded_numbers(text: str, facts: dict) -> list[float]:
    text = _WINDOW.sub(" ", text)
    fact_nums = _flatten(facts)
    bad = []
    for val, pct, unit in _numbers_in(text):
        cands = [(val, unit), (val / 100.0, unit / 100.0)] if pct else [(val, unit)]
        if not any(_matches(c, u, f) for c, u in cands for f in fact_nums):
            bad.append(val)
    return bad


def numbers_grounded(text: str, facts: dict) -> bool:
    return not ungrounded_numbers(text, facts)


def no_advice(text: str) -> bool:
    return not _ADVICE.search(text)


def no_links(text: str) -> bool:
    return not _LINK.search(text)


def clean_name(s: str | None, limit: int = 40) -> str:
    """Third-party text (coin names) is untrusted: strip control chars and cap length before it reaches a
    prompt, a Slack payload or an email."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()[:limit]
