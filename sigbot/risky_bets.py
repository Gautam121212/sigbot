"""Risky speculative bets — sized to magnitude, for both stocks and crypto.

The user's point: the risky bets were vague — nothing said "this could move
significantly, put a small amount on it." This ties the magnitude signal (how
BIG the move could be) to an actual sized speculative bet, for stocks and crypto.

The logic:
  - Magnitude says how big the move could be (regime-independent, direction-blind).
  - A direction hint (the model's own weak lean) picks a side.
  - Together they define a SMALL bet: big potential move + a direction lean =
    a lottery ticket sized to the potential, never more than 1% of capital.

This is deliberately separate from the proven signals. Proven signals (like
panic-capitulation) get real size; these risky bets get tiny size because the
edge is unproven — they exist to LEARN (feed the risk loop) and to catch the
occasional big asymmetric move, not to carry the account.
"""
from __future__ import annotations

from dataclasses import dataclass

from .magnitude import is_high_magnitude, magnitude


@dataclass(frozen=True)
class RiskyBet:
    asset: str
    side: str                   # "BUY" / "SELL" — the weak direction lean
    expected_move_pct: float    # how big the move could be
    size_pct: float             # % of capital (small, capped at 1%)
    rationale: str


def evaluate_risky(asset: str, *, atr_pct: float | None, volume_ratio: float | None,
                   rsi: float | None, mom20: float | None,
                   direction_lean: str | None, crypto: bool = False
                   ) -> RiskyBet | None:
    """A risky bet only when the move could be BIG (magnitude) and there's a
    direction lean to pick a side. Otherwise None — no bet."""
    mag = magnitude(atr_pct, volume_ratio, rsi, mom20, crypto=crypto)
    if not is_high_magnitude(mag) or direction_lean not in ("BUY", "SELL"):
        return None
    return RiskyBet(
        asset=asset, side=direction_lean,
        expected_move_pct=round(mag.expected_move * 100, 1),
        size_pct=mag.bet_size_pct,
        rationale=(f"{mag.note}; leaning {direction_lean} — small speculative "
                   f"bet ({mag.bet_size_pct}% of capital) on a potentially big move"))


# ---- News / ideas / ventures risky bets ----------------------------------
# These are not price series, so "magnitude" is domain-specific:
#   news    -> the earnings-surprise size (a huge surprise moves ~1.8x a small one)
#   ideas   -> the thesis strength (how many checks it passed)
#   venture -> the payoff asymmetry (upside multiple with capped downside)
# Each produces a small speculative bet sized to that magnitude, capped low.

# Measured: earnings surprise size -> absolute move (all three periods).
#   small (<5%): ~4% move | huge (40%+): ~7.9% move. Monotonic.
NEWS_MOVE_BY_SURPRISE = ((40.0, 0.079), (15.0, 0.062), (5.0, 0.049), (0.0, 0.042))


def news_magnitude(abs_surprise_pct: float | None) -> float:
    """Expected absolute move from an earnings surprise's SIZE (not direction).
    Regime-independent: a bigger surprise reliably causes a bigger move."""
    if abs_surprise_pct is None:
        return 0.042
    for threshold, move in NEWS_MOVE_BY_SURPRISE:
        if abs_surprise_pct >= threshold:
            return move
    return 0.042


def news_risky_bet(symbol: str, abs_surprise_pct: float | None,
                   direction: str | None) -> RiskyBet | None:
    """A risky news bet when the surprise is big enough to move the stock and
    there is a direction. Sized to the surprise magnitude, capped small."""
    move = news_magnitude(abs_surprise_pct)
    if move < 0.06 or direction not in ("BUY", "SELL"):
        return None                 # only bet on surprises big enough to matter
    size = 0.5 if move >= 0.075 else 0.25
    return RiskyBet(
        asset=symbol, side=direction, expected_move_pct=round(move * 100, 1),
        size_pct=size,
        rationale=(f"earnings surprise implies ~{move * 100:.0f}% move; "
                   f"leaning {direction} — small speculative bet ({size}% capital)"))


def venture_risky_bet(name: str, upside_multiple: float | None,
                      downside_capped: bool, ev_multiple: float | None
                      ) -> RiskyBet | None:
    """A risky venture bet on the barbell logic: capped downside + large upside +
    positive expected value = a small asymmetric bet. The 'magnitude' is the
    upside multiple; the bet is tiny because the probability is unknown."""
    if not downside_capped or upside_multiple is None or upside_multiple < 3.0:
        return None                 # need a genuinely asymmetric payoff
    if ev_multiple is None or ev_multiple <= 0:
        return None                 # and positive expected value
    # Bigger upside -> a slightly bigger (still tiny) barbell bet.
    size = 1.0 if upside_multiple >= 10 else 0.5
    return RiskyBet(
        asset=name, side="BUY", expected_move_pct=round(upside_multiple * 100, 0),
        size_pct=size,
        rationale=(f"{upside_multiple:.0f}x upside, downside capped, "
                   f"EV +{ev_multiple:.1f} — small asymmetric bet ({size}% capital)"))


def idea_risky_bet(title: str, checks_passed: int, checks_total: int,
                   direction: str = "BUY") -> RiskyBet | None:
    """A risky idea bet: the more checks a thesis has passed, the more it is
    worth a small speculative position. 'Magnitude' is thesis conviction."""
    if checks_total < 1 or checks_passed < checks_total:
        return None                 # only fully-checked ideas get a bet
    size = 0.5 if checks_total >= 3 else 0.25
    return RiskyBet(
        asset=title[:40], side=direction, expected_move_pct=0.0,
        size_pct=size,
        rationale=(f"thesis passed all {checks_total} checks — "
                   f"small speculative bet ({size}% capital)"))


def direction_lean(rsi: float | None, mom20: float | None) -> str | None:
    """A weak direction hint for sizing a risky bet: oversold+falling leans BUY
    (bounce), overbought+rising leans SELL (fade). Deliberately simple — the
    edge is in the MAGNITUDE, the direction is just a coin-flip tiebreak."""
    if rsi is None:
        return None
    if rsi < 30:
        return "BUY"            # oversold — lean to a bounce
    if rsi > 70:
        return "SELL"           # overbought — lean to a fade
    return None
