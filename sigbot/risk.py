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

# Most positions allowed in one sector at a time.
#
# The heat ceiling above counts POSITIONS, and positions are only independent
# until they are not. Measured on the real signal history: on an average day
# 67% of everything that fired came from a single sector, 184 days produced
# four or more in one sector, and the worst single day fired 263 signals at
# once — which happens precisely during a market-wide fall, exactly when
# correlations go to one.
#
# Six positions at 1% each is 6% of risk only if they are six different bets.
# Four of them in the same sector is closer to three bets, and in a crash it
# is one. Without this cap the heat ceiling understates real exposure at the
# only moment the number matters.
MAX_PER_SECTOR = 2

# Share of the account that may be committed at once. Not a risk limit — a
# funding one. Leaving a quarter uncommitted also means a gap through a stop
# does not force a sale elsewhere to cover it.
MAX_DEPLOYED = 0.75

# Most positions open at once, whatever the sector. A day that fires 263
# signals is not an opportunity, it is a market-wide event, and taking all of
# them is one enormous directional bet wearing the costume of diversification.
MAX_OPEN_POSITIONS = 6


@dataclass(frozen=True)
class RiskState:
    """Everything needed to decide whether, and how large, to trade."""

    equity: float
    open_risk: float = 0.0          # fraction of capital at risk right now
    deployed: float = 0.0           # cash already committed to open positions
    open_positions: int = 0
    sector_positions: int = 0       # already open in THIS trade's sector
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

    if state.sector_positions >= MAX_PER_SECTOR:
        return Decision(False, 0.0, 0.0,
                        f"Already holding {state.sector_positions} position(s) "
                        "in this sector. On an average day two thirds of all "
                        "signals come from one sector, so more than a couple "
                        "is one bet in several costumes.")

    if state.open_positions >= MAX_OPEN_POSITIONS:
        return Decision(False, 0.0, 0.0,
                        f"{state.open_positions} positions already open. A day "
                        "that fires a hundred signals is a market-wide event, "
                        "not a hundred opportunities.")

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

    # RISK and CAPITAL are different constraints, and only one of them was
    # being checked. A dry run of thirty simultaneous signals took four
    # positions at 4% total risk — correct — while committing 67% of the
    # account. Six would have needed more cash than exists.
    #
    # Risk is what a position can lose; capital is what it costs to hold.
    # Tight stops produce large positions at small risk, so a book can be
    # fully within its risk budget and still unfundable.
    free = max(0.0, state.equity * MAX_DEPLOYED - state.deployed)
    if free <= 0:
        return Decision(False, 0.0, 0.0,
                        f"{state.deployed:,.0f} of {state.equity:,.0f} is "
                        "already committed. Risk is within budget but there "
                        "is no cash left — a tight stop makes a position "
                        "cheap in risk and expensive in capital.")
    size = min(size, free)

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
        f"  Per sector            at most {MAX_PER_SECTOR} positions — "
        "two thirds of signals come from one sector on an average day",
        f"  Open positions        at most {MAX_OPEN_POSITIONS} at once",
        f"  Capital committed     at most {MAX_DEPLOYED * 100:.0f}% of the "
        "account — risk and cash are different limits",
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
