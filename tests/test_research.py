"""The research protocol, and the capitulation setup it produced."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sigbot.research import (
    PENDING, REGIME_ROUND, ROUND_3, ROUND_3_BATCH, ROUND_4, ROUND_4_BATCH, SWEEP_1, SWEEP_1_BATCH, Result,
    bonferroni_t, survives,
)
from sigbot.runner import market_regime
from sigbot.scan import CANDIDATES, scan_row


def test_the_bar_rises_with_the_number_of_tests():
    """Test more, and chance produces more false winners — so the bar rises."""
    assert 1.9 < bonferroni_t(1) < 2.0
    assert bonferroni_t(38) > 3.1
    assert bonferroni_t(500) > bonferroni_t(38)


def test_only_one_of_the_first_sweep_survives():
    survivors = [r.hypothesis for r in SWEEP_1 if survives(r, SWEEP_1_BATCH)]
    assert survivors == ["Williams %R below -90"]


def test_a_signal_that_flips_sign_never_survives_however_strong():
    """MACD crossovers: t 8.5 in discovery, then -5.6. Strength in one period
    is not evidence; consistency across periods is."""
    flip = Result("x", 8.5, -5.6, 1.5, (0.33, -0.24, 0.04))
    assert not survives(flip, SWEEP_1_BATCH)


def test_a_weak_discovery_does_not_survive_on_strong_confirmations():
    assert not survives(Result("x", 2.0, 11.9, 10.0, (0.1, 0.6, 0.5)), SWEEP_1_BATCH)


def test_oversold_is_consistent_only_in_a_volatile_decline():
    consistent = {r.hypothesis for r in REGIME_ROUND if all(x > 0 for x in r.excess_pct)}
    assert all("volatile decline" in h for h in consistent)
    assert not any("calm rise" in h for h in consistent)


def test_market_regime_reads_calm_rises_and_crashes():
    rng = np.random.default_rng(1)
    calm = pd.Series(100 * np.cumprod(1 + 0.0005 + rng.normal(0, 0.005, 400)))
    crash = pd.Series(list(calm) + list(calm.iloc[-1] * np.cumprod(
        1 - 0.01 + rng.normal(0, 0.03, 60))))
    assert market_regime(calm) == "up/calm"
    assert market_regime(crash) == "down/volatile"
    assert market_regime(calm.head(100)) is None, "too little history fails closed"


def test_capitulation_fires_only_in_a_volatile_decline():
    row = {"willr_14": -95.0, "volume_ma_20": 2_000_000, "close": 50.0}
    hit = scan_row("X", {**row, "index_regime": "down/volatile"})
    assert hit and hit.candidate.name == "capitulation"
    for regime in ("up/calm", "up/volatile", "down/calm", None):
        h = scan_row("X", {**row, "index_regime": regime})
        assert not h or h.candidate.name != "capitulation", regime


def test_capitulation_is_a_satellite_setup_but_not_called_proven():
    from sigbot.runner import SATELLITE_STYLES
    from sigbot.scan import PROVEN, tier_of

    cap = next(c for c in CANDIDATES if c.name == "capitulation")
    assert cap.style in SATELLITE_STYLES and cap.hold_days == 20
    assert tier_of(cap) != PROVEN, "second-round finding with clustered evidence"



def test_round_3_adopts_only_what_survived():
    """The three hypotheses written down in advance: one survives."""
    verdicts = {r.hypothesis: survives(r, ROUND_3_BATCH) for r in ROUND_3}
    assert verdicts == {
        "Capitulation held 20 days (vs 5 and 10)": True,
        "Insider cluster buying, liquid stocks, 20 days": False,
        "Earnings big miss in a volatile decline, 20 days": False,
    }


def test_the_next_round_is_written_down_before_it_is_run():
    assert len(PENDING) >= 2
    assert all("all three periods" in h for h in PENDING)



def test_round_4_momentum_survives_only_in_a_calm_uptrend():
    verdicts = {r.hypothesis: survives(r, ROUND_4_BATCH) for r in ROUND_4}
    assert verdicts["Momentum | calm uptrend"] is True
    assert not any(v for h, v in verdicts.items() if h != "Momentum | calm uptrend")


def test_a_consistent_loser_is_labelled_avoid_never_adopt():
    """The protocol checks consistency; direction must be checked too, or a
    strategy that lost in every period is printed as a survivor."""
    from sigbot.research import ROUND_5, ROUND_5_BATCH, label

    labels = {r.hypothesis: label(r, ROUND_5_BATCH) for r in ROUND_5}
    assert labels["Low-volatility anomaly (bottom 10% vol)"] == "AVOID"
    assert labels["Capitulation, beta-adjusted"] == "ADOPT"
    assert labels["Far below 52w high | volatile decline, beta-adj"] == "HELD BACK"
    assert labels["Follow-on rebound, beta-adjusted (5 days)"] == "fails"


def test_follow_on_is_expected_to_have_no_edge():
    """Its rebound was beta. Expecting an edge would teach the loop to credit luck."""
    from sigbot.calibration import EXPECTED
    from sigbot.promotion import MODEL_VERDICTS

    assert EXPECTED["contagion"][0] == 0.0
    assert MODEL_VERDICTS["contagion"][0] == "NO"


def test_round_6_adopts_the_confirmed_surprise_and_nothing_else():
    from sigbot.research import ROUND_6, ROUND_6_BATCH, label

    labels = {r.hypothesis: label(r, ROUND_6_BATCH) for r in ROUND_6}
    assert labels["Confirmed surprise: big beat + 2% rise on the day"] == "ADOPT"
    assert all(v != "ADOPT" for k, v in labels.items()
               if not k.startswith("Confirmed surprise"))


def test_confirmed_surprise_needs_both_the_beat_and_the_market_agreeing():
    from sigbot.indicators import confirmed_surprise

    assert confirmed_surprise(15.0, 0.03)
    assert not confirmed_surprise(15.0, -0.03), "the market disagreed"
    assert not confirmed_surprise(5.0, 0.03), "not a big beat"
    assert not confirmed_surprise(-15.0, 0.03), "misses are not used"
    assert not confirmed_surprise(None, 0.03) and not confirmed_surprise(15.0, None)
