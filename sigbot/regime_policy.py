"""Regime-aware signal selection — read the market first, then pick the signal.

THE PRINCIPLE
-------------
Every edge this project found is regime-dependent: it works in some market
states and inverts in others. So instead of firing every signal always and
hoping the per-signal guards catch the bad cases, sigbot reads the market
regime FIRST and only activates the signals proven to work in that regime.

This is the "read the situation, then choose the perfect indicator" fix.

THE MAP (from regime testing across crashes, rallies, ranges x volatility)
--------------------------------------------------------------------------
  down/volatile (a crash):  capitulation, hammer, accumulation, confirmed-surprise
                            all pay MOST here — the disaster-buying edges.
  up/calm (a quiet rally):  momentum only; the dip-buyers INVERT here (they
                            lose), so they are switched off.
  down/calm | up/volatile:  the mixed middle — only the signals that stayed
                            positive in that exact state fire.

A signal not listed for the current regime does not fire, even if its own
condition is met. This is stricter than the per-signal guards and encodes the
measured truth: the same pattern means opposite things in different weather.
"""
from __future__ import annotations

# For each regime, the signals allowed to fire. Names match scan.py candidates
# and the crypto/news signal ids. Empty = nothing fires (stand aside).
#
# Derived from measured regime returns:
#   capitulation  : +0.53% (t 8.0) ONLY in down/volatile
#   hammer        : +1.17% down/volatile, +0.27% up/volatile, LOSES up/calm
#   accumulation  : +0.21% (t 4.9) volatile ranges, LOSES up/calm (-0.83%)
#   momentum      : positive ONLY in up/calm
#   confirmed-surprise (news): +0.87% down/volatile, fades in calm
STOCK_POLICY: dict[str, frozenset[str]] = {
    "down/volatile": frozenset({"capitulation", "hammer-in-downtrend",
                                "accumulation-divergence", "oversold-money-holding",
                                "hard-down-day", "extreme-williams",
                                "stretched-below-trend"}),
    "up/volatile": frozenset({"hammer-in-downtrend", "accumulation-divergence"}),
    "down/calm": frozenset({"accumulation-divergence"}),
    "up/calm": frozenset({"momentum-breakout"}),
}

# Crypto signals by regime (crypto has no index; its own trend/vol is the regime).
#   low-volume drop / below-7d-MA : disaster-buyers, fire in crashes
#   crowding (avoid)              : fires in complacent states to STAND ASIDE
CRYPTO_BUY_REGIMES = frozenset({"down/volatile", "down/calm"})   # dip-buyers here
CRYPTO_AVOID_REGIMES = frozenset({"up/calm", "range/volatile"})  # crowding avoid here


def stock_signals_allowed(regime: str | None) -> frozenset[str]:
    """The stock signals that may fire in this regime. Unknown regime -> only
    the most robust disaster signal, capitulation, and nothing speculative."""
    if regime is None:
        return frozenset({"capitulation"})
    return STOCK_POLICY.get(regime, frozenset())


def signal_allowed(signal_name: str, regime: str | None) -> bool:
    """Whether a specific stock signal may fire given the current regime."""
    return signal_name in stock_signals_allowed(regime)


def crypto_should_buy(crypto_regime: str | None) -> bool:
    """Dip-buying crypto signals fire only in the regimes where they paid."""
    return crypto_regime in CRYPTO_BUY_REGIMES


def crypto_should_avoid(crypto_regime: str | None) -> bool:
    """The crowding-avoid signal is meaningful only in complacent regimes."""
    return crypto_regime in CRYPTO_AVOID_REGIMES


def regime_summary(regime: str | None) -> str:
    """A plain-language line for the page: what the market is and what fires."""
    if regime is None:
        return "Market state unread — only the most robust signal is active."
    allowed = stock_signals_allowed(regime)
    mood = {
        "down/volatile": "a volatile decline — the disaster-buying signals are active",
        "up/volatile": "a choppy uptrend — only the sturdier reversal signals fire",
        "down/calm": "a quiet drift down — only accumulation fires",
        "up/calm": "a calm rally — only momentum fires; dip-buyers are off",
    }.get(regime, "an unclassified state")
    return f"Market is {mood} ({len(allowed)} signal(s) active)."
