"""The playbook and the code must say the same thing.

PLAYBOOK.md is the reference the system is measured against. A reference that
drifts from the code is worse than none, because it reports the intended
behaviour while the system does something else — the same failure as B80, B83
and B84, one level up. These tests fail when a number in the playbook and the
constant in the code disagree.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "PLAYBOOK.md").read_text()
# The sigbot-vs-trader comparison, where the code's constants are quoted.
BOOK = (ROOT / "COMPARISON.md").read_text()


def test_the_guide_covers_exactly_sigbots_five_models():
    for section in ("News scanner", "Stocks", "Crypto", "Opportunities",
                    "Follow-on moves"):
        assert f"· {section}" in GUIDE, f"playbook is missing {section}"


def test_the_guide_contains_no_sigbot_rules():
    """It is a guidebook of how traders work, drawn from many of them. Sigbot's
    behaviour belongs in COMPARISON.md, or the guide stops being a reference
    and becomes a description of the thing it is meant to judge."""
    for internal in ("RiskState", "LOSS_STREAK", "scan_row", "shadow.db",
                     "conviction_pct", "sigbot.", "priority.py"):
        assert internal not in GUIDE, f"sigbot internals leaked into the guide: {internal}"


def test_the_guide_draws_on_many_traders_not_one():
    for trader in ("O'Neil", "Minervini", "Weinstein", "Livermore", "Connors",
                   "Buffett", "Munger", "Lynch", "Greenblatt", "Druckenmiller"):
        assert trader in GUIDE, f"{trader} missing"


def test_the_guide_gives_both_sides_where_traders_disagree():
    assert "Where professionals disagree" in GUIDE
    assert "momentum" in GUIDE.lower() and "mean-reversion" in GUIDE.lower()


def test_every_section_states_its_evidence():
    """A claim without an evidence tag is exactly how untested professional
    rules got adopted and then inverted."""
    for tag in ("TESTED", "SOURCED", "UNTESTABLE HERE", "REJECTED"):
        assert tag in BOOK
    assert BOOK.count("**Evidence:**") >= 5


def test_risk_numbers_match_the_code():
    from sigbot.risk import (
        DAILY_LOSS_LIMIT, LOSS_STREAK_PAUSE, MAX_DEPLOYED,
        MAX_OPEN_POSITIONS, MAX_PER_SECTOR, RISK_PER_TRADE,
    )

    assert RISK_PER_TRADE == 0.01 and "1% of capital" in BOOK
    assert LOSS_STREAK_PAUSE == 4 and "Pause after 4" in BOOK
    assert DAILY_LOSS_LIMIT == 0.03 and "| 3% |" in BOOK
    assert MAX_PER_SECTOR == 2 and MAX_OPEN_POSITIONS == 6
    assert "≤2 per sector, ≤6 open" in BOOK
    assert MAX_DEPLOYED == 0.75 and "≤75% deployed" in BOOK


def test_exit_and_liquidity_numbers_match_the_code():
    from sigbot.exits import STOP_ATR_MULTIPLE, TARGET_ATR_MULTIPLE
    from sigbot.scan import MIN_AVG_VOLUME

    assert STOP_ATR_MULTIPLE == 3.0 and "3×ATR" in BOOK
    assert TARGET_ATR_MULTIPLE is None and "no target" in BOOK
    assert MIN_AVG_VOLUME == 500_000 and "≥500k shares/day" in BOOK


def test_rejected_rules_are_off_in_the_code():
    from sigbot.scan import REGIME_FILTER

    assert "REJECTED on this setup" in BOOK
    assert REGIME_FILTER is False


def test_crypto_gets_momentum_but_never_dip_buying():
    """Crypto washouts returned -3.64% over five days against -0.39% for any
    day, so dip-buying stays out. The first guard refused crypto entirely and
    so also blocked momentum — the one style the playbook says suits it."""
    from sigbot.scan import scan_row

    washout = {"rsi_14": 15.0, "mfi_14": 30.0, "volume_ma_20": 5_000_000,
               "close": 50.0}
    breakout = {"close": 110.0, "hi52": 108.0, "sma_50": 100.0,
                "sma_200": 90.0, "volume": 3_000_000, "volume_ma_20": 1_000_000,
                "index_regime": "up/calm"}
    for sym in ("BTC-USD", "ETH-USD", "SOLUSDT"):
        assert scan_row(sym, washout) is None, sym
        hit = scan_row(sym, breakout)
        assert hit is not None and hit.candidate.style == "momentum", sym
    assert scan_row("AAPL", washout) is not None, "stocks still buy washouts"


def test_the_momentum_school_is_held_to_the_same_bar():
    """+0.098 R against the washout setup's +0.043 R, positive in all three
    eras — but behind simply holding in 2016-19. The bar that demoted the
    washout setup has to demote this too, or it is not a rule."""
    from sigbot.scan import CANDIDATES, RISKY, tier_of

    mom = next(c for c in CANDIDATES if c.name == "momentum-breakout")
    assert mom.eras_positive == 3 and not mom.beats_holding
    assert tier_of(mom) == RISKY


def test_the_stated_edge_is_the_one_measured():
    for figure in ("+0.042 R", "+0.241 R", "−0.559 R", "+1.424%"):
        assert figure in BOOK, f"{figure} missing — the playbook has drifted"
