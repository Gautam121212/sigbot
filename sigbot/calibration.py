"""Live results against what history predicted — the learning-gap check.

A backtest makes a prediction about the future. This compares each model's
live record with that prediction and says whether they agree. Agreement
confirms the history; disagreement is a learning gap to investigate, in
either direction — a model doing BETTER than history predicted is as much a
signal that something is misunderstood as one doing worse.

The first check found exactly that: news scored 57.5% on 80 live checks
against 46.9% chance, while 58,000 earnings reports said news is priced in on
the day. Either luck, or sigbot's news is not like earnings news. Only more
live checks can tell which.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from math import sqrt

CONSISTENT, DIVERGENT, EARLY = "CONSISTENT", "DIVERGENT", "TOO EARLY"
MIN_CHECKS = 50
Z_FLAG = 1.64          # about one-sided 5%: worth a look, not a conclusion

# model -> (what history predicted, as an edge over chance in hit rate,
#           and where that prediction came from)
EXPECTED: dict[str, tuple[float, str]] = {
    "crypto15m": (0.0, "no short-term edge in either direction (CoinGecko, GBTC)"),
    "daily": (0.0, "no edge over 141,123 replayed decisions"),
    "news": (0.0, "priced on the day across 58,000 earnings reports"),
    # The rebound looked positive in all three periods, but after removing
    # each stock's own beta it was -0.14% / +0.11% / +0.11% — below costs and
    # flipping sign. Expecting an edge would teach the loop to credit luck.
    "contagion": (0.0, "rebound was beta to the market, not an edge"),
    "stocks": (0.02, "capitulation and calm-uptrend momentum beat the index"),
}


@dataclass(frozen=True)
class Gap:
    model: str
    checks: int
    live_edge: float        # live hit rate minus the base rate
    expected_edge: float
    z: float
    verdict: str
    source: str


def base_rate(con, model: str) -> float:
    """The chance rate the model is measured against: its own share of up
    outcomes, so a model is not credited for a rising market."""
    row = con.execute("SELECT AVG(CASE WHEN exit_price > entry_price THEN 1.0 ELSE 0.0 END) "
                      "FROM predictions WHERE model=? AND hit IS NOT NULL "
                      "AND entry_price > 0 AND exit_price > 0", (model,)).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.5


def check(db_path: str) -> list[Gap]:
    out = []
    with closing(sqlite3.connect(db_path)) as con:
        for model, (expected, source) in EXPECTED.items():
            n, hits = con.execute("SELECT COUNT(*), SUM(hit) FROM predictions "
                                  "WHERE model=? AND hit IS NOT NULL", (model,)).fetchone()
            n = int(n or 0)
            if n < MIN_CHECKS:
                out.append(Gap(model, n, 0.0, expected, 0.0, EARLY, source))
                continue
            chance = min(max(base_rate(con, model), 0.05), 0.95)
            live = (hits or 0) / n - chance
            se = sqrt(chance * (1 - chance) / n)
            z = (live - expected) / se if se else 0.0
            verdict = DIVERGENT if abs(z) >= Z_FLAG else CONSISTENT
            out.append(Gap(model, n, live, expected, z, verdict, source))
    return out


def describe(gaps: list[Gap]) -> str:
    lines = ["Learning gaps — live results against what history predicted", ""]
    for g in gaps:
        if g.verdict == EARLY:
            lines.append(f"  [{g.verdict:<10}] {g.model:<10} {g.checks} checks")
            continue
        lines.append(f"  [{g.verdict:<10}] {g.model:<10} {g.checks} checks, live edge "
                     f"{g.live_edge * 100:+.1f} pts vs expected {g.expected_edge * 100:+.1f} "
                     f"(z {g.z:+.1f}) — history: {g.source}")
    if any(g.verdict == DIVERGENT for g in gaps):
        lines.append("")
        lines.append("  A divergence is a question, not a verdict: luck, a changed "
                     "market, or a model that is not doing what history measured.")
    return "\n".join(lines)
