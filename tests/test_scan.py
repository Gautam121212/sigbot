"""The wide scan and its two-tier gate.

The risky tier is the learning mechanism, and it is the part most likely to
decay into "let more through". These tests pin the properties that stop it.
"""
from __future__ import annotations

from sigbot.scan import (
    CANDIDATES,
    PROVEN,
    RISKY,
    Candidate,
    position_size,
    scan_row,
    summarise,
    tier_of,
)


def _c(eras, edge, n=10000, name="x"):
    return Candidate(name=name, side="BUY", plain="p",
                     condition=lambda row: True, pooled_edge_pp=edge,
                     pooled_n=n, eras_positive=eras)


def test_proven_needs_consistency_AND_a_real_edge():
    """Three positive eras on +0.3pp is consistency without profit; +15pp in
    one era out of three is the gap-down trap. Both halves are required."""
    assert tier_of(_c(3, 5.0)) == PROVEN
    assert tier_of(_c(3, 0.3)) == RISKY, "consistent but not worth trading"
    assert tier_of(_c(1, 15.0)) == RISKY, "one era is not evidence"
    assert tier_of(_c(2, 5.4)) == RISKY, "two of three is still unproven"


def test_conviction_is_mostly_era_consistency():
    """Era consistency separated every real finding from every false one in
    the sweep. Sample size and edge size are necessary and, alone, lie."""
    consistent_small = _c(3, 3.0, n=500)
    huge_but_lucky = _c(1, 15.0, n=200_000)
    assert consistent_small.conviction_pct > huge_but_lucky.conviction_pct


def test_risky_rows_are_sized_down_not_hidden():
    """The whole reason the risky tier can exist is that being wrong on it
    costs a fraction. Hiding it instead would forfeit the learning."""
    row = {"rsi_14": 18.0, "mfi_14": 30.0}
    proven_hit = scan_row("AAPL", row)
    assert proven_hit is not None and proven_hit.tier == PROVEN

    risky_row = {"close": 70.0, "sma_200": 100.0}
    risky_hit = scan_row("XYZ", risky_row)
    assert risky_hit is not None and risky_hit.tier == RISKY

    base = 10_000.0
    assert position_size(risky_hit, base) < position_size(proven_hit, base) / 2


def test_a_proven_reason_beats_a_risky_one_on_the_same_name():
    """A name is never labelled risky when there is a proven reason to hold
    it — that would understate the evidence and mis-size the position."""
    both = {"rsi_14": 18.0, "mfi_14": 30.0, "close": 70.0, "sma_200": 100.0}
    hit = scan_row("AAPL", both)
    assert hit is not None and hit.tier == PROVEN


def test_only_two_colours_ever():
    """Green or grey. A third state would reintroduce the amber problem: a
    colour that sorts high while meaning "not yet"."""
    rows = [
        {"rsi_14": 18.0, "mfi_14": 30.0},          # proven
        {"close": 70.0, "sma_200": 100.0},          # risky
        {"willr_14": -99.0},                        # risky
        {"close": 90.0, "prev_close": 100.0},       # risky
    ]
    seen = {hit.colour for hit in (scan_row("S", r) for r in rows) if hit}
    assert seen == {"var(--green)", "var(--faint)"}, seen


def test_silence_is_reported_as_normal_not_as_failure():
    text = summarise([], looked=2500)
    assert "Nothing fired" in text
    assert "costs nothing" in text


def test_the_shipped_candidates_carry_their_measurements():
    for c in CANDIDATES:
        assert c.pooled_n > 1000, f"{c.name} rests on too little data"
        assert 0 <= c.eras_positive <= 3
        assert c.plain and not c.plain.startswith("TODO")
