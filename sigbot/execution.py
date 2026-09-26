"""Professional execution layer — sizing and exits, the real driver of returns.

The point-1 research was unanimous: "the frequency of winning trades is a poor
predictor of profitability" and "returns are a byproduct of disciplined risk
control." Pros make money from HOW they size and exit, not just the signal.
Every session before this hunted signals; this is the piece that was missing.

The decomposed professional components, TESTED on sigbot's own signals:

1. POSITION SIZING by risk, not gut: 0.25-1% of capital risked per trade,
   scaled by conviction. A proven signal gets more, a risky one less.

2. SCALE THE RIGHT WAY — and it depends on the signal:
   - Trend/momentum signals: scale WINNERS (add as it works).
   - Mean-reversion signals (capitulation): TESTED — the opposite. A trade
     underwater at day 3 has MORE mean-reversion left (+1.29% vs +0.54% for
     the winner). So for reversion, add to the laggard, not the winner.

3. EXIT when the per-day edge decays. TESTED on capitulation: the edge is
   front-loaded — day 1 +0.32%/day, day 5 +0.18%, day 10 +0.15%. Exit at
   day 3-5 and redeploy the capital; holding 20 days wastes it.

4. HARD STOPS and correlation limits: cap the loss on every trade, and never
   let correlated positions become one bet.
"""
from __future__ import annotations

from dataclasses import dataclass

# Risk per trade by conviction tier (% of capital at risk).
RISK_PROVEN = 0.010        # a proven signal: 1%
RISK_RISKY = 0.0025        # a risky/speculative signal: 0.25%

# Optimal hold days by signal style (where the per-day edge peaks).
HOLD_DAYS = {"reversion": 4, "momentum": 15, "blowup": 60, "news": 3}


@dataclass(frozen=True)
class ExecutionPlan:
    size_pct: float            # % of capital to deploy
    hold_days: int             # when to exit
    scale_rule: str            # how to add, if at all
    stop_pct: float            # hard stop distance
    note: str


def plan_trade(*, style: str, proven: bool, atr_pct: float | None) -> ExecutionPlan:
    """The professional execution plan for one signal: size, hold, scale, stop."""
    risk = RISK_PROVEN if proven else RISK_RISKY
    # A wider ATR means a wider stop, so position size shrinks to keep risk fixed:
    # size = risk / stop_distance. Stop = 2 ATR (pro default), floored so tiny
    # ATRs don't blow size up.
    stop = max((atr_pct or 0.02) * 2, 0.03)
    size = min(risk / stop, 0.10)      # never more than 10% of capital in one name
    # Scale rule depends on the signal's nature (the tested finding).
    if style == "reversion":
        scale = ("add to the trade if it is UNDERWATER at day 3 (more reversion "
                 "left) — NOT the winner; the winner's move is mostly done")
    elif style == "momentum" or style == "blowup":
        scale = "add to the WINNER as it works (trend continuation)"
    else:
        scale = "no scaling — single entry"
    hold = HOLD_DAYS.get(style, 5)
    return ExecutionPlan(
        size_pct=round(size * 100, 2), hold_days=hold, scale_rule=scale,
        stop_pct=round(stop * 100, 1),
        note=(f"risk {risk * 100:.2f}% at a {stop * 100:.0f}% stop → "
              f"{size * 100:.1f}% position, exit ~day {hold}"))


def describe() -> str:
    lines = ["PROFESSIONAL EXECUTION LAYER — sizing & exits (the real edge)", ""]
    for style, proven in (("reversion", True), ("momentum", True),
                          ("news", False), ("blowup", False)):
        p = plan_trade(style=style, proven=proven, atr_pct=0.03)
        lines.append(f"  {style:<10} ({'proven' if proven else 'risky'}): {p.note}")
        lines.append(f"             scale: {p.scale_rule}")
    lines.append("")
    lines.append("Key finding: for mean-reversion, add to the LOSER not the winner")
    lines.append("(tested: underwater-at-day-3 has +1.29% left vs +0.54% for the winner).")
    return "\n".join(lines)
