"""Live health monitor — detect process drift symmetrically, pause, never tweak."""
from sigbot.live_health_monitor import (
    HealthLedger, HealthState, LiveBehaviour, assess,
    monitor_allows_trading)


def _live(win=59.4, sig=12.0, pos=4.0, drag=30.0, dd=10.0):
    return LiveBehaviour(win, sig, pos, drag, dd)


# ── the core distinction: loss within distribution is NOT drift ─────────────
def test_drawdown_within_validated_distribution_is_healthy():
    """Down 20% with normal process = unlucky, not drifting. Do not pause."""
    r = assess(_live(win=57, dd=20.0))
    assert r.state == HealthState.HEALTHY
    assert monitor_allows_trading(r.state)


def test_drawdown_beyond_validated_worstcase_quarantines():
    """Only a DD beyond the validated 95th-pct (~40%) is material drift."""
    r = assess(_live(dd=48.0))
    assert r.state == HealthState.QUARANTINED
    assert not monitor_allows_trading(r.state)


# ── symmetry: drifting ABOVE the band is drift too ──────────────────────────
def test_suspicious_hot_streak_is_drift():
    """Win rate 92% + signals 5x = making money the wrong way = drift."""
    r = assess(_live(win=92, sig=55))
    assert r.state == HealthState.QUARANTINED
    dirs = {f.direction for f in r.findings}
    assert "above" in dirs


def test_win_rate_far_below_band_is_drift():
    r = assess(_live(win=40))          # band is 59.4 +/- 12
    assert any(f.characteristic == "win_rate" for f in r.findings)


# ── single vs multiple characteristics ──────────────────────────────────────
def test_single_characteristic_drift_is_warning():
    r = assess(_live(drag=90))         # only execution drag off
    assert r.state == HealthState.WARNING


def test_two_characteristics_drift_quarantines():
    r = assess(_live(win=90, sig=60))
    assert r.state == HealthState.QUARANTINED


# ── execution drag ──────────────────────────────────────────────────────────
def test_execution_drag_blowout_flagged():
    r = assess(_live(drag=100))
    assert any(f.characteristic == "execution_drag_bps" for f in r.findings)


# ── position concentration ──────────────────────────────────────────────────
def test_position_concentration_drift_flagged():
    r = assess(_live(pos=9.0))         # band is 4.0 +/- 3
    assert any(f.characteristic == "avg_position_pct" for f in r.findings)


# ── clean state ─────────────────────────────────────────────────────────────
def test_normal_behaviour_is_healthy():
    r = assess(_live())
    assert r.state == HealthState.HEALTHY
    assert not r.findings


# ── the monitor never tweaks ────────────────────────────────────────────────
def test_monitor_has_no_strategy_mutation_method():
    import sigbot.live_health_monitor as m
    assert not hasattr(m, "adjust_strategy")
    assert not hasattr(m, "retune")
    assert not hasattr(m, "fix_drift")


def test_assess_returns_report_not_a_new_strategy():
    """assess only reports — it cannot return a modified strategy."""
    r = assess(_live(win=40))
    assert hasattr(r, "state") and hasattr(r, "findings")
    assert not hasattr(r, "new_parameters")


# ── ledger ──────────────────────────────────────────────────────────────────
def test_ledger_preserves_quarantine_events():
    led = HealthLedger()
    led.append(assess(_live()))
    led.append(assess(_live(dd=48.0)))     # quarantine
    led.append(assess(_live()))
    assert len(led.quarantines()) == 1
    assert len(led.all()) == 3             # append-only, nothing overwritten


def test_quarantine_blocks_trading_via_monitor_gate():
    r = assess(_live(win=95, sig=60))
    assert not monitor_allows_trading(r.state)
