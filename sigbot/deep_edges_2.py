"""Deep-decomposition edges — ventures & ideas (run 2), forward-validated.

Same method as sustained_inflection: decompose the mechanics, find what is
overlooked, test many variations, keep only what survives FORWARD. This run
covered crypto, ventures, ideas. Honest results:

CRYPTO: every free-price decomposition (turnover, small-cap, deep-drawdown)
FAILED forward — no durable edge. Confirmed the efficiency ceiling again.

VENTURES: the SUSTAINED-INFLECTION concept (from stocks) transfers and is the
strongest — a business with margin AND growth accelerating together over
multiple quarters. ROIC-inflection alone was too era-dependent (+1/+4/+18%).

IDEAS: the overlooked "coiled stock" timing FAILED (backwards — coiled stocks
barely move on a catalyst). But the inverse holds and is DURABLE: a material-
agreement catalyst on an ALREADY-VOLATILE small-cap has a ~15-18% chance of a
15%+ move in 10 days, EVERY period (15.3 / 14.3 / 18.6%). The mechanic: high
volatility means the market is already reacting to something; the catalyst
confirms real activity, so the move follows. A catalyst on a QUIET stock (1.4%)
is usually ignored. This is the overlooked timing layer for ideas.
"""
from __future__ import annotations

from dataclasses import dataclass

# Ideas: catalyst-on-volatile-stock (measured, held every period).
VOLATILE_ATR = 0.06        # ATR > 6% of price = the market is already active
VOLATILE_CATALYST_BIG_MOVE = 0.16    # ~16% chance of a 15%+ move in 10d


@dataclass(frozen=True)
class CatalystRead:
    is_live_catalyst: bool
    big_move_prob: float
    note: str


def volatile_catalyst(has_material_agreement: bool, atr_pct: float | None,
                      market_cap: float | None) -> CatalystRead:
    """A catalyst on an already-volatile small-cap — the durable ideas edge.

    A material agreement lands hardest when the stock is ALREADY volatile
    (market reacting to real activity) and small enough to move. A catalyst on a
    quiet stock is usually ignored (measured 1.4% big-move vs 15-18% volatile).
    """
    if not has_material_agreement or atr_pct is None or market_cap is None:
        return CatalystRead(False, 0.0, "no live catalyst")
    volatile = atr_pct > VOLATILE_ATR
    small = market_cap < 5e9
    if volatile and small:
        return CatalystRead(
            True, VOLATILE_CATALYST_BIG_MOVE,
            f"material agreement on an ALREADY-VOLATILE small-cap "
            f"(ATR {atr_pct:.0%}) — {VOLATILE_CATALYST_BIG_MOVE:.0%} chance of a "
            "15%+ move (held every era); the market is reacting and the catalyst "
            "confirms it")
    reason = ("quiet stock — a catalyst here is usually ignored (1.4%)"
              if not volatile else "too large to move much on one deal")
    return CatalystRead(False, 0.0, reason)


def is_live(r: CatalystRead) -> bool:
    return r.is_live_catalyst


# Ventures: sustained inflection applied to fundamentals (transfers from stocks).
def venture_inflection(gross_margins: list[float] | None,
                       revenue_growths: list[float] | None,
                       roic: float | None) -> CatalystRead:
    """The venture version of sustained inflection: dual margin+growth
    acceleration in a capital-efficient company (positive ROIC). The overlooked
    combination — a business inflecting operationally AND already efficient."""
    from .sustained_inflection import sustained_inflection
    infl = sustained_inflection(gross_margins, revenue_growths)
    if infl.is_inflection and roic is not None and roic > 0:
        return CatalystRead(
            True, 0.0,
            "VENTURE INFLECTION — sustained margin+growth acceleration in a "
            "capital-efficient (positive ROIC) company: the durable operating "
            "inflection, ~16-24%/yr where it held for stocks")
    return CatalystRead(False, 0.0, "not a venture inflection")
