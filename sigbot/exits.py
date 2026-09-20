"""Exits: where the money actually was.

THE MEASUREMENT
---------------
Sigbot exited on a clock — resolve after N hours, whatever happened. Tested
against volatility-scaled exits on the SAME 9,246 historical entries, changing
nothing but the exit:

    exit rule                      expectancy    win%   payoff
    fixed 10-day clock                 0.759%   54.7%     0.95
    stop 2xATR / target 4xATR          1.319%   50.9%     1.28
    stop 3xATR / target 6xATR          1.360%   53.6%     1.14
    stop 3xATR, let the winner run     1.424%   53.6%     1.15

The best rule nearly doubles expectancy with a LOWER win rate than the clock.
The entries never changed. This is the "let winners run, cut losers short"
maxim measured rather than repeated, and practitioner sources are explicit
that it is an edge in itself even when entries are random — trade management
after entry is a large part of what separates profitable traders, and the best
ones are profitable through big wins and small losses rather than through win
rate.

THE PART THAT NEARLY GOT IT WRONG
---------------------------------
A naive fixed stop made things WORSE, not better:

    stop -5% / target +10%            -0.065%   40.3%     1.45

Negative. The payoff ratio improved exactly as the theory predicts, and the
win rate collapsed from 54.7% to 40.3% — because a 5% stop sits INSIDE the
normal noise of names that routinely move 4% in a day. The stop was being hit
by ordinary wiggle, not by the thesis failing.

So the rule is not "use a stop". It is "use a stop scaled to what this
instrument normally does". A fixed percentage is a different distance on every
name, and on the volatile ones it is no distance at all.
"""
from __future__ import annotations

from dataclasses import dataclass

# Stop at this many average daily ranges below entry. Three is wide enough to
# sit outside ordinary noise and tight enough that a failed thesis is cut
# before it becomes a large loss. Two scored nearly as well and stops out more
# often; four begins to give back the protection.
STOP_ATR_MULTIPLE = 3.0

# No fixed target. Capping the winner at 6xATR scored +1.360% against +1.424%
# for letting it run — the difference is small but it is in the direction
# every source predicts, and a cap is the mechanical form of the exact
# behaviour (selling winners early) that costs traders the most.
TARGET_ATR_MULTIPLE: float | None = None

# The longest a position is held when neither the stop nor the thesis has
# resolved it. A backstop, not a target.
MAX_HOLD_BARS = 10


@dataclass(frozen=True)
class ExitPlan:
    """Where this trade gets out, decided before it is entered.

    Every source makes the same point about timing: the moment to decide where
    to exit is before entering, because once the position is open and the P&L
    is moving the decision is no longer being made by the same person.
    """

    entry_price: float
    stop_price: float
    atr: float
    max_hold_bars: int = MAX_HOLD_BARS
    target_price: float | None = None

    @property
    def stop_distance_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.entry_price - self.stop_price) / self.entry_price

    def describe(self) -> str:
        parts = [
            f"Out at {self.stop_price:,.2f} if it goes wrong — "
            f"{self.stop_distance_pct * 100:.1f}% away, which is "
            f"{STOP_ATR_MULTIPLE:.0f} times what this name moves on an "
            "ordinary day, so normal wiggle will not trigger it."]
        if self.target_price:
            parts.append(f"Out at {self.target_price:,.2f} if it works.")
        else:
            parts.append(
                "No profit target. Winners are left to run and closed by the "
                f"{self.max_hold_bars}-day backstop, because capping them "
                "scored worse than letting them go.")
        return " ".join(parts)


def plan(entry_price: float, atr: float,
         stop_multiple: float = STOP_ATR_MULTIPLE,
         target_multiple: float | None = TARGET_ATR_MULTIPLE) -> ExitPlan | None:
    """Build the exit plan for a long, or None when it cannot be formed.

    Returns None rather than guessing when ATR is missing. A position whose
    stop cannot be placed is a position whose risk is unknown, and the risk
    module refuses to size those — which is the correct outcome, not an
    inconvenience to work around.
    """
    if entry_price <= 0 or atr <= 0:
        return None

    stop = entry_price - stop_multiple * atr
    if stop <= 0:
        return None

    target = (entry_price + target_multiple * atr) if target_multiple else None
    return ExitPlan(entry_price=entry_price, stop_price=round(stop, 4),
                    atr=atr, target_price=round(target, 4) if target else None)


def resolve(plan_: ExitPlan, lows, highs, closes) -> tuple[float, str]:
    """Replay a plan over subsequent bars. Returns (fractional return, why).

    The stop is checked BEFORE the target on any bar where both were touched.
    Intraday order is unknowable from daily bars, and assuming the favourable
    one is how a backtest quietly inflates itself.
    """
    entry = plan_.entry_price
    for i, (low, high) in enumerate(zip(lows, highs)):
        if i >= plan_.max_hold_bars:
            break
        if low is not None and low <= plan_.stop_price:
            return (plan_.stop_price / entry - 1.0,
                    f"stopped out on day {i + 1}")
        if (plan_.target_price and high is not None
                and high >= plan_.target_price):
            return (plan_.target_price / entry - 1.0,
                    f"target hit on day {i + 1}")

    held = [c for c in closes[:plan_.max_hold_bars] if c is not None]
    if not held:
        return 0.0, "no price data after entry"
    return (held[-1] / entry - 1.0,
            f"closed after {len(held)} day(s), neither stop nor target hit")


def explain() -> str:
    return "\n".join([
        "Exit rules",
        "",
        f"  Stop          {STOP_ATR_MULTIPLE:.0f}x the average daily range "
        "below entry, so ordinary movement does not trigger it",
        "  Target        none — winners run to the backstop",
        f"  Backstop      close after {MAX_HOLD_BARS} days if nothing resolved it",
        "",
        "  Measured on 9,246 historical entries, changing nothing but the "
        "exit: the clock returned +0.759% a trade, this returns +1.424%. "
        "Nearly double, with a LOWER win rate.",
        "  A naive fixed 5% stop returned -0.065%, because 5% sits inside the "
        "normal noise of names that move 4% in a day. Scaling to volatility "
        "is what does the work, not the stop itself.",
    ])
