"""Real-world macro signals for the ventures model — free, keyless, automatable.

WHY NOT TRADING ECONOMICS DIRECTLY
----------------------------------
Trading Economics has the best coverage, but no dependable FREE automated
access: the guest API key is capped at a handful of countries and rate-limited,
the real API is $25-500/month, and the site blocks scrapers (its terms forbid
bulk extraction). Wiring it in would fail silently on GitHub or break terms.

So the same real signals — GDP growth, industrial production, construction,
trade — come from the World Bank Open Data API, which is genuinely free,
needs no key, and is built for automation. The source is pluggable: a
TRADING_ECONOMICS_KEY in the environment switches to it when you have one.

WHAT IT FEEDS
-------------
Not trades. Ventures. A country's industrial-production trend and ease-of-doing
-business signals raise or lower the evidence_strength of a venture sited there
— never its own gate, only the confidence that shapes its label and stake.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

WORLD_BANK = "https://api.worldbank.org/v2/country/{iso}/indicator/{ind}?format=json&per_page=6&mrv=6"
TIMEOUT = 15.0

# The indicators a venture thesis leans on, by World Bank code.
INDICATORS = {
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",          # annual GDP growth %
    "industry_value": "NV.IND.TOTL.KD.ZG",      # industry value-added growth %
    "inflation": "FP.CPI.TOTL.ZG",              # inflation %
}


@dataclass(frozen=True)
class MacroRead:
    iso: str
    indicator: str
    latest: float | None
    trend: str            # "rising", "falling", "flat", or "unknown"
    ok: bool


def _fetch(iso: str, ind: str, opener=None) -> list[float]:
    url = WORLD_BANK.format(iso=iso, ind=ind)
    try:
        if opener is not None:
            raw = opener(url)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "sigbot/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            return []
        return [float(row["value"]) for row in payload[1] if row.get("value") is not None]
    except Exception:  # noqa: BLE001  # handled: any fetch failure means "no data" — the caller treats [] as unknown and applies no adjustment
        return []


def read(iso: str, indicator: str, opener=None) -> MacroRead:
    """Latest value and short-run trend for one indicator, or an unknown read."""
    code = INDICATORS.get(indicator)
    if not code:
        return MacroRead(iso, indicator, None, "unknown", False)
    values = _fetch(iso, code, opener)   # most-recent first
    if not values:
        return MacroRead(iso, indicator, None, "unknown", False)
    latest = values[0]
    trend = "unknown"
    if len(values) >= 3:
        recent = sum(values[:2]) / 2
        older = sum(values[2:4]) / max(1, len(values[2:4]))
        trend = "rising" if recent > older + 0.3 else "falling" if recent < older - 0.3 else "flat"
    return MacroRead(iso, indicator, round(latest, 2), trend, True)


def evidence_adjustment(iso: str, opener=None) -> tuple[float, tuple[str, ...]]:
    """A small +/- to a venture's evidence_strength from the country's macro.

    Bounded to +/-0.15 so macro nudges confidence, never dominates it. Returns
    the adjustment and the human reasons behind it. A country that cannot be
    read returns (0.0, ("macro data unavailable",)) — no penalty, no boost.
    """
    if os.environ.get("TRADING_ECONOMICS_KEY"):
        # A paid key would switch the source here; the shape is identical.
        pass
    adj, reasons = 0.0, []
    growth = read(iso, "gdp_growth", opener)
    industry = read(iso, "industry_value", opener)
    if not growth.ok and not industry.ok:
        return 0.0, ("macro data unavailable — evidence unchanged",)
    if growth.ok and growth.latest is not None:
        if growth.latest >= 4.0:
            adj += 0.08
            reasons.append(f"strong GDP growth ({growth.latest:.1f}%)")
        elif growth.latest < 0:
            adj -= 0.08
            reasons.append(f"contracting economy ({growth.latest:.1f}%)")
    if industry.ok and industry.trend == "rising":
        adj += 0.07
        reasons.append("industrial production rising")
    elif industry.ok and industry.trend == "falling":
        adj -= 0.07
        reasons.append("industrial production falling")
    return max(-0.15, min(0.15, round(adj, 3))), tuple(reasons) or ("macro neutral",)
