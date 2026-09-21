"""The circuit breakers must fire from REAL results, not a hand-built state.

Three of five breakers were permanently dead in the live scan: it built its
risk state as RiskState(equity=100_000.0) and never read the ledger, so the
losing streak, today's P&L and the high-water mark were always their defaults.
Every rule was correct, tested in isolation, and switched off by that line.
These tests go through the ledger on purpose — the unit tests that passed all
along built RiskState by hand, which is exactly how the gap stayed hidden.
"""
from __future__ import annotations

from sigbot.risk import decide
from sigbot.runner import _seed_risk_state
from sigbot.shadow import ShadowLedger


class _S:
    def __init__(self, path):
        self.shadow_db = str(path)


def _lose(ledger, n, symbol="X"):
    for _ in range(n):
        pid = ledger.record("stocks", symbol, "BUY", 0.7, 0.05, 100.0)
        ledger.resolve(pid, 90.0)


def test_a_real_losing_streak_is_counted(tmp_path):
    settings = _S(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    _lose(ledger, 4)
    assert ledger.current_loss_streak("stocks") == 4


def test_a_win_ends_the_streak(tmp_path):
    settings = _S(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    _lose(ledger, 3)
    pid = ledger.record("stocks", "W", "BUY", 0.7, 0.05, 100.0)
    ledger.resolve(pid, 110.0)
    assert ledger.current_loss_streak("stocks") == 0


def test_the_breakers_fire_through_the_live_seeding(tmp_path):
    """Four losses on the same day trip BOTH the daily limit and the streak
    pause; the daily limit is checked first. Before this fix neither could
    fire at all, because the state was never read from the ledger."""
    settings = _S(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    _lose(ledger, 4)

    state = _seed_risk_state(ledger, settings)
    assert state.loss_streak == 4
    assert state.day_pnl_pct < -0.03
    assert not decide(state, entry_price=100.0, stop_price=94.0).allowed


def test_the_streak_pause_fires_on_its_own(tmp_path):
    """Isolated from the daily limit: trades after four straight losses
    returned -0.559 R historically, and this is the breaker that avoids them."""
    from dataclasses import replace

    settings = _S(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    _lose(ledger, 4)

    state = replace(_seed_risk_state(ledger, settings), day_pnl_pct=0.0)
    d = decide(state, entry_price=100.0, stop_price=94.0)
    assert not d.allowed and "in a row" in d.reason


def test_drawdown_is_measured_from_real_equity(tmp_path):
    """The throttle needs a high-water mark; it was never set."""
    settings = _S(tmp_path / "s.db")
    ledger = ShadowLedger(settings.shadow_db)
    _lose(ledger, 2)

    state = _seed_risk_state(ledger, settings)
    assert state.peak_equity is not None
    assert state.equity < state.peak_equity, "losses must show as drawdown"


def test_an_empty_ledger_starts_clean_rather_than_blocking(tmp_path):
    settings = _S(tmp_path / "s.db")
    ShadowLedger(settings.shadow_db)
    state = _seed_risk_state(ledger=ShadowLedger(settings.shadow_db),
                             settings=settings)
    assert state.loss_streak == 0
    assert decide(state, 100.0, 94.0).allowed
