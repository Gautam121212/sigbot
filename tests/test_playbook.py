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
BOOK = (ROOT / "PLAYBOOK.md").read_text()


def test_every_model_has_a_section():
    for section in ("News scanner", "Daily outlook", "Follow-on moves",
                    "Crypto", "Opportunities", "Ideas", "Paper trading",
                    "Stocks (after paper trading)"):
        assert f"· {section}" in BOOK, f"playbook is missing {section}"


def test_every_section_states_its_evidence():
    """A claim without an evidence tag is exactly how untested professional
    rules got adopted and then inverted."""
    for tag in ("TESTED", "SOURCED", "UNTESTABLE HERE", "REJECTED"):
        assert tag in BOOK
    assert BOOK.count("**Evidence:**") >= 7


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


def test_the_washout_setup_never_fires_on_crypto():
    """Crypto washouts returned -3.64% over five days against -0.39% for any
    day. The stocks setup would lose money there."""
    from sigbot.scan import scan_row

    washout = {"rsi_14": 15.0, "mfi_14": 30.0, "volume_ma_20": 5_000_000}
    for sym in ("BTC-USD", "ETH-USD", "SOLUSDT"):
        assert scan_row(sym, washout) is None, sym
    assert scan_row("AAPL", washout) is not None, "stocks still fire"


def test_the_stated_edge_is_the_one_measured():
    for figure in ("+0.042 R", "+0.241 R", "−0.559 R", "+1.424%"):
        assert figure in BOOK, f"{figure} missing — the playbook has drifted"
