"""Returns in dollars on a $100k account — money is the clearest measure.

The user's point: percentages are abstract; dollars on $100,000 are legible.
This translates each model's real record into what it would have made or lost
on a $100k account, per trade and per day, so "does this model make money" has
a number instead of a hit rate.

Position sizing: each trade risks 2% of capital ($2,000 on $100k) — a standard
conservative size. The dollar figure is the realised return times that stake.
Only CLEAN, resolved trades count (corrupt rows and micro-price artifacts are
excluded, so the number reflects the real edge, not bad data).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass

CAPITAL = 100_000
POSITION_PCT = 0.02             # 2% of capital per trade
STAKE = CAPITAL * POSITION_PCT  # $2,000


@dataclass(frozen=True)
class ModelMoney:
    model: str
    trades: int
    win_rate: float
    dollar_per_trade: float
    dollar_total: float
    dollar_per_day: float


def model_money(db_path: str) -> list[ModelMoney]:
    out = []
    with closing(sqlite3.connect(db_path)) as con:
        models = [r[0] for r in con.execute(
            "SELECT DISTINCT model FROM predictions ORDER BY model")]
        for m in models:
            # Clean resolved trades only — exclude corrupt/micro-price rows.
            rows = con.execute(
                "SELECT realised_ret, hit, created_at FROM predictions "
                "WHERE model=? AND hit IS NOT NULL AND realised_ret IS NOT NULL "
                "AND ABS(realised_ret) <= 0.5", (m,)).fetchall()
            if len(rows) < 20:
                continue
            rets = [r[0] for r in rows]
            n = len(rets)
            wins = sum(1 for r in rets if r > 0)
            per_trade = sum(rets) / n * STAKE
            total = sum(r * STAKE for r in rets)
            # span in days for a per-day figure
            days = {str(r[2])[:10] for r in rows if r[2]}
            per_day = total / max(len(days), 1)
            out.append(ModelMoney(m, n, wins / n, round(per_trade, 2),
                                  round(total, 0), round(per_day, 2)))
    return out


def describe(db_path: str) -> str:
    lines = [f"Returns in dollars on a ${CAPITAL:,} account "
             f"(${STAKE:,.0f} per trade, clean trades only):", ""]
    rows = model_money(db_path)
    if not rows:
        lines.append("  No model has enough clean resolved trades yet.")
        return "\n".join(lines)
    for r in rows:
        sign = "makes" if r.dollar_total >= 0 else "LOSES"
        lines.append(
            f"  {r.model:<11} {r.trades} trades, {r.win_rate:.0%} win → "
            f"${r.dollar_per_trade:+,.2f}/trade, ${r.dollar_per_day:+,.2f}/day, "
            f"{sign} ${abs(r.dollar_total):,.0f} total")
    return "\n".join(lines)
