"""Risk discipline: the part professionals spend most of their attention on.

WHY THIS EXISTS
---------------
Every model in this system decides WHAT to trade. Not one of them decided HOW
MUCH, or WHEN TO STOP. That inversion is the documented difference between
professionals and everyone else: practitioner sources put it at roughly 80% of
a professional's mental energy on risk management and 20% on entries, with
amateurs doing the reverse — obsessing over signals while ignoring sizing,
stops and total exposure.

The arithmetic is the reason, and it is unforgiving. A ten-trade losing streak
arrives for everyone eventually. At 1% risk per trade it costs 10% of capital
and is survivable. At 10% risk per trade the same streak is terminal. No
quality of trade selection compensates for position risk set too high, because
ruin is absorbing: an account at zero does not recover when the edge returns.

WHAT THE SOURCES AGREE ON
-------------------------
  * Risk 1-2% of capital per trade, with 1% preferred and 2% the ceiling.
    Experienced prop traders commonly run 0.5-1%.
  * Size the POSITION from the stop distance so that RISK stays constant.
    A tight stop permits a large position at the same risk; a wide stop
    demands a small one. Sizing by conviction instead lets a confident read
    on a volatile name quietly become the largest risk in the book.
  * Cap total open risk across all positions, not just per trade.
  * After consecutive losses, REDUCE exposure. Increasing to recover is the
    single most reliably destructive response, because it raises risk exactly
    when the evidence that conditions have changed is strongest.
  * Set a daily loss limit that ends the session, so a bad day cannot compound
    into a bad month.

A NOTE ON WHAT THIS CORRECTS
----------------------------
An earlier version of the paper model sized positions by conviction. That is
not how a desk works and it is subtly dangerous: conviction and volatility
are correlated — the most compelling setups tend to appear in the most violent
conditions — so conviction-weighted sizing systematically puts the most money
where the widest swings are. Risk-based sizing does the opposite, and the
deep-oversold setup is exactly the case that proves the point: high accuracy,
violent conditions, and a payoff ratio of 1.08.
"""
from __future__ import annotations

from dataclasses import dataclass

# Fraction of capital risked on one trade. 1% is the practitioner default:
# it survives a fifty-trade losing streak, which 2% does not comfortably do.
RISK_PER_TRADE = 0.01

# Total risk allowed across every open position at once. Eight simultaneous
# trades at 1% is already a bad week if they correlate, and in a drawdown they
# always correlate.
MAX_PORTFOLIO_HEAT = 0.06

# Consecutive losses that pause new entries. Not a prediction that the next
# one loses — an admission that the reason for the streak is unknown, and that
# finding out is cheaper than paying for it.
LOSS_STREAK_PAUSE = 4

# Loss in a single day that ends the day. A limit that stops the session
# before the urge to make it back does the deciding.
DAILY_LOSS_LIMIT = 0.03


@dataclass(frozen=True)
class RiskState:
    """Everything needed to decide whether, and how large, to trade."""

    equity: float
    open_risk: float = 0.0          # fraction of capital at risk right now
    loss_streak: int = 0
    day_pnl_pct: float = 0.0        # today's realised P&L, as a fraction
    peak_equity: float | None = None

    @property
    def drawdown_pct(self) -> float:
        """How far below the high-water mark, as a fraction."""
        peak = self.peak_equity or self.equity
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - self.equity) / peak)


@dataclass(frozen=True)
class Decision:
    """Whether to take a trade, at what size, and why."""

    allowed: bool
    size: float                     # cash to commit, 0 when not allowed
    risk_fraction: float            # capital actually put at risk
    reason: str


def _risk_budget(state: RiskState) -> float:
    """Risk permitted on the next trade, after drawdown throttling.

    Halved in a meaningful drawdown and halved again in a deep one. This is
    the direction the sources are unanimous about and the direction instinct
    argues against: after losses, reduce. Increasing to recover raises risk
    precisely when the evidence that something has changed is strongest, and
    it is the most reliable way to turn a bad month into a terminal one.
    """
    budget = RISK_PER_TRADE
    if state.drawdown_pct >= 0.20:
        budget *= 0.25
    elif state.drawdown_pct >= 0.10:
        budget *= 0.5
    return budget


def decide(state: RiskState, entry_price: float, stop_price: float,
           ) -> Decision:
    """Size a position from its stop, or refuse it.

    The position is whatever makes the distance to the stop equal the risk
    budget. That is the whole idea: risk is held constant and SIZE varies,
    rather than size being held constant and risk varying with volatility.
    """
    if entry_price <= 0 or stop_price <= 0:
        return Decision(False, 0.0, 0.0,
                        "No usable price. A trade without a known stop has "
                        "no known risk and cannot be sized.")

    if stop_price >= entry_price:
        return Decision(False, 0.0, 0.0,
                        "The stop is not below the entry, so this trade has "
                        "no defined loss. Refused.")

    if state.day_pnl_pct <= -DAILY_LOSS_LIMIT:
        return Decision(False, 0.0, 0.0,
                        f"Down {abs(state.day_pnl_pct) * 100:.1f}% today, "
                        f"past the {DAILY_LOSS_LIMIT * 100:.0f}% daily limit. "
                        "The day is over — a limit that stops the session "
                        "before the urge to make it back does the deciding.")

    if state.loss_streak >= LOSS_STREAK_PAUSE:
        return Decision(False, 0.0, 0.0,
                        f"{state.loss_streak} losses in a row. New entries "
                        "are paused — not because the next one must lose, but "
                        "because the reason for the streak is unknown and "
                        "finding out is cheaper than paying for it.")

    budget = _risk_budget(state)
    if state.open_risk + budget > MAX_PORTFOLIO_HEAT:
        return Decision(False, 0.0, 0.0,
                        f"Already risking {state.open_risk * 100:.1f}% across "
                        f"open positions, against a {MAX_PORTFOLIO_HEAT * 100:.0f}% "
                        "ceiling. Positions that look independent stop being "
                        "independent in a drawdown.")

    stop_distance = (entry_price - stop_price) / entry_price
    if stop_distance <= 0.001:
        return Decision(False, 0.0, 0.0,
                        "The stop sits within a tenth of a percent of the "
                        "entry. Normal noise would trigger it, so the "
                        "position it implies is absurdly large. Refused.")

    size = state.equity * budget / stop_distance
    # Never let one position exceed a quarter of the book, however tight the
    # stop. A stop can gap through; the risk calculation assumes it will not.
    size = min(size, state.equity * 0.25)

    note = ""
    if budget < RISK_PER_TRADE:
        note = (f" Risk cut to {budget * 100:.2f}% of capital while "
                f"{state.drawdown_pct * 100:.0f}% below the high-water mark.")

    return Decision(
        True, round(size, 2), budget,
        f"Risking {budget * 100:.2f}% of capital with a stop "
        f"{stop_distance * 100:.1f}% away, which sizes the position at "
        f"{size:,.0f}.{note}")


def explain() -> str:
    """The rules, in the order they are checked."""
    return "\n".join([
        "Risk rules, applied before any trade",
        "",
        f"  Risk per trade        {RISK_PER_TRADE * 100:.0f}% of capital, "
        "sized from the stop distance",
        f"  Total open risk       {MAX_PORTFOLIO_HEAT * 100:.0f}% ceiling "
        "across all positions at once",
        f"  Losing streak         pause new entries after "
        f"{LOSS_STREAK_PAUSE} in a row",
        f"  Daily loss limit      stop for the day at "
        f"{DAILY_LOSS_LIMIT * 100:.0f}%",
        "  In drawdown           halve risk past 10%, quarter it past 20%",
        "",
        "  A ten-trade losing streak arrives for everyone. At 1% risk it "
        "costs 10% of capital and is survivable; at 10% risk the same streak "
        "is terminal. No quality of trade selection compensates for position "
        "risk set too high, because an account at zero does not recover when "
        "the edge returns.",
    ])
