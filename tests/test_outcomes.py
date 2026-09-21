"""Year-by-year outcomes, and the crypto regime rule."""
from __future__ import annotations

from sigbot.outcomes import (
    CRYPTO_AVOID_PANIC, CRYPTO_HOLD, CRYPTO_RISK_ON_ONLY, FOLLOW_NEW, FOLLOW_OLD,
    STOCKS_NEW, STOCKS_OLD, YEARS, describe, growth, mean, trailing_decay, years_positive,
)
from sigbot.runner import crypto_exposure


def test_every_series_covers_every_year():
    for s in (STOCKS_OLD, STOCKS_NEW, FOLLOW_OLD, FOLLOW_NEW):
        assert len(s) == len(YEARS)


def test_the_new_stock_strategy_is_steadier_than_the_old():
    assert years_positive(STOCKS_NEW) > years_positive(STOCKS_OLD)
    assert mean(STOCKS_NEW, skip_first=True) > mean(STOCKS_OLD, skip_first=True)


def test_the_rebound_beats_following_but_its_decay_is_flagged():
    """The yearly list found what the averages hid: 2022-2025 all negative."""
    assert mean(FOLLOW_NEW) > mean(FOLLOW_OLD)
    assert trailing_decay(FOLLOW_NEW)
    assert "DECAY" in describe()


def test_avoiding_stock_panics_compounds_best_and_risk_on_only_fails():
    assert growth(CRYPTO_AVOID_PANIC) > growth(CRYPTO_HOLD) > growth(CRYPTO_RISK_ON_ONLY)


def test_crypto_exposure_follows_the_stock_market_regime():
    assert crypto_exposure("down/volatile") == "STAND ASIDE"
    for regime in ("up/calm", "up/volatile", "down/calm", None):
        assert crypto_exposure(regime) == "HOLD"


def test_selectivity_is_not_judged_on_one_run():
    """597 looks — one run — produced a false DRIFT on a user's machine."""
    from sigbot.alignment import EARLY, check_selectivity
    assert check_selectivity(597, 77).verdict == EARLY
