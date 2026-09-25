"""Self-referential signals — edges from sigbot's own ledger."""
from __future__ import annotations

from sigbot.self_signals import CONFIRMED, form_multiplier, recent_form
from sigbot.shadow import ShadowLedger


def _seed(db, model, hits):
    led = ShadowLedger(db)
    for i, h in enumerate(hits):
        pid = led.record(model, f"{model}{i}", "BUY", 0.6, 0.02, 100.0)
        led.resolve(pid, 101.0 if h else 99.0)


def test_recent_form_reads_the_last_window(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db, "daily", [1] * 15 + [0] * 5)     # last 20: 75% then... newest are the 0s
    form = recent_form(db, "daily", window=20)
    assert form is not None and 0 <= form <= 1


def test_a_hot_confirmed_model_is_sized_up(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db, "daily", [0] * 5 + [1] * 20)     # newest 20 all wins = hot
    mult, why = form_multiplier(db, "daily")
    assert mult > 1.0 and "in form" in why


def test_a_cold_confirmed_model_is_sized_down(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db, "daily", [1] * 5 + [0] * 20)     # newest 20 all losses = cold
    mult, why = form_multiplier(db, "daily")
    assert mult < 1.0 and "out of form" in why


def test_an_unconfirmed_model_is_never_adjusted(tmp_path):
    """Only models whose form-momentum held out-of-sample get a multiplier."""
    db = str(tmp_path / "s.db")
    _seed(db, "crypto15m", [1] * 20)
    mult, why = form_multiplier(db, "crypto15m")
    assert mult == 1.0 and "not confirmed" in why
    assert "crypto15m" not in CONFIRMED


def test_too_little_history_is_neutral(tmp_path):
    db = str(tmp_path / "s.db")
    _seed(db, "daily", [1] * 5)                # fewer than a window
    mult, _ = form_multiplier(db, "daily")
    assert mult == 1.0
