"""The wide scan and its two-tier gate.

The risky tier is the learning mechanism, and it is the part most likely to
decay into "let more through". These tests pin the properties that stop it.
"""
from __future__ import annotations

from sigbot.scan import (
    CANDIDATES,
    Hit,
    PROVEN,
    RISKY,
    Candidate,
    position_size,
    scan_row,
    summarise,
    tier_of,
)


def _c(eras, edge, n=10000, name="x", beats_holding=True):
    return Candidate(name=name, side="BUY", plain="p",
                     condition=lambda row: True, pooled_edge_pp=edge,
                     pooled_n=n, eras_positive=eras,
                     beats_holding=beats_holding, payoff_ratio=1.6)


def test_proven_needs_consistency_AND_a_real_edge():
    """Three positive eras on +0.3pp is consistency without profit; +15pp in
    one era out of three is the gap-down trap. Both halves are required."""
    assert tier_of(_c(3, 5.0)) == PROVEN
    assert tier_of(_c(3, 0.3)) == RISKY, "consistent but not worth trading"
    assert tier_of(_c(1, 15.0)) == RISKY, "one era is not evidence"
    assert tier_of(_c(2, 5.4)) == RISKY, "two of three is still unproven"
    assert tier_of(_c(3, 5.0, beats_holding=False)) == RISKY, (
        "accurate, consistent, and still worse than doing nothing")


def test_nothing_currently_ships_as_proven():
    """The honest state after the money test. Deep-oversold wins 54.3% against
    51.1% across three eras and still earns +0.599% a trade where holding
    earns +0.659% — the extra accuracy is bought with exactly enough extra
    downside to more than cancel it. An empty proven tier is the correct
    output, not a bug to design around."""
    from sigbot.scan import CANDIDATES

    assert all(tier_of(c) == RISKY for c in CANDIDATES)
    # Capitulation beats the index within its regime in all three periods,
    # measured beyond the index over the same days — the first candidate to.
    # It stays RISKY: a second-round finding whose evidence clusters on panic
    # days. Nothing else beats holding.
    assert [c.name for c in CANDIDATES if c.beats_holding] == ["capitulation"]


def test_conviction_is_mostly_era_consistency():
    """Era consistency separated every real finding from every false one in
    the sweep. Sample size and edge size are necessary and, alone, lie."""
    consistent_small = _c(3, 3.0, n=500)
    huge_but_lucky = _c(1, 15.0, n=200_000)
    assert consistent_small.conviction_pct > huge_but_lucky.conviction_pct


def test_risky_rows_are_sized_down_not_hidden():
    """The whole reason the risky tier can exist is that being wrong on it
    costs a fraction. Hiding it instead would forfeit the learning."""
    from sigbot.scan import Hit

    base = 10_000.0
    proven = Hit("A", _c(3, 5.0), PROVEN, 100.0, 1.0, "r")
    risky = Hit("B", _c(2, 5.0, beats_holding=False), RISKY, 78.0, 1.0, "r")
    assert position_size(risky, base) < position_size(proven, base) / 2


def test_a_proven_reason_beats_a_risky_one_on_the_same_name():
    """A name is never labelled risky when there is a proven reason to hold
    it — that would understate the evidence and mis-size the position."""
    both = {"rsi_14": 18.0, "mfi_14": 30.0, "close": 70.0, "sma_200": 100.0,
            "volume_ma_20": 2_000_000}
    hit = scan_row("AAPL", both)
    assert hit is not None
    # Highest conviction wins when no candidate is proven, which is the
    # current state — the strongest available reason, honestly labelled.
    assert hit.candidate.name == "oversold-money-holding"


def test_only_two_colours_ever():
    """Green or grey. A third state would reintroduce the amber problem: a
    colour that sorts high while meaning "not yet"."""
    liquid = {"volume_ma_20": 2_000_000}
    rows = [
        {"rsi_14": 18.0, "mfi_14": 30.0, **liquid},
        {"close": 70.0, "sma_200": 100.0, **liquid},
        {"willr_14": -99.0, **liquid},
        {"close": 90.0, "prev_close": 100.0, **liquid},
    ]
    hits = [h for h in (scan_row("S", r) for r in rows) if h]
    # Non-empty on purpose. With the liquidity filter added, rows lacking
    # volume returned nothing and `seen <= {...}` passed on an EMPTY set — a
    # test asserting nothing while reporting green.
    assert hits, "these rows must fire, or the colour check tests nothing"
    seen = {h.colour for h in hits}
    assert seen <= {"var(--green)", "var(--faint)"}, seen
    # And the palette itself only ever offers those two.
    assert Hit("S", _c(3, 5.0), PROVEN, 100.0, 1.0, "r").colour == "var(--green)"
    assert Hit("S", _c(1, 5.0, beats_holding=False), RISKY, 20.0, 1.0,
               "r").colour == "var(--faint)"


def test_silence_is_reported_as_normal_not_as_failure():
    text = summarise([], looked=2500)
    assert "Nothing fired" in text
    assert "costs nothing" in text


def test_the_shipped_candidates_carry_their_measurements():
    for c in CANDIDATES:
        assert c.pooled_n > 1000, f"{c.name} rests on too little data"
        assert 0 <= c.eras_positive <= 3
        assert c.plain and not c.plain.startswith("TODO")


def test_a_setup_cannot_buy_accuracy_with_bigger_losses():
    """The failure that demoted the only proven candidate. A setup can raise
    its hit rate by trading conditions where being wrong is expensive, and
    every accuracy-based test will applaud it."""
    from sigbot.expectancy import compare_to_holding

    # Deep-oversold as measured: 54.3% wins at +4.47%, losses at -4.12%.
    setup = [0.0447] * 543 + [-0.0412] * 457
    # Any random session: 51.1% wins at +2.97%, losses at -1.79%.
    hold = [0.0297] * 511 + [-0.0179] * 489

    c = compare_to_holding(setup, hold)
    assert c.payoff_ratio < 1.2, "wins barely bigger than losses"
    assert c.edge_pct < 0, "and therefore worse than doing nothing"
    assert not c.beats_holding
    assert "WORSE than doing nothing" in c.verdict()


def test_holding_is_the_benchmark_not_zero():
    """A setup that makes money in a rising market has not necessarily done
    anything. Benchmarking against zero flatters every one of them."""
    from sigbot.expectancy import compare_to_holding

    setup = [0.01] * 300
    strong_market = [0.02] * 300
    assert compare_to_holding(setup, strong_market).edge_pct < 0
    assert compare_to_holding(setup, []).edge_pct > 0, (
        "the same setup looks good against a zero benchmark")



def test_thin_names_are_never_traded():
    """Names averaging under 500k shares a day returned +1.136% against
    +1.514% for liquid ones on the same entries. Thin names gap harder through
    stops and cost more to fill, so their paper results overstate reality."""
    row = {"rsi_14": 18.0, "mfi_14": 30.0, "volume_ma_20": 100_000, "close": 50.0}
    assert scan_row("THIN", row) is None
    assert scan_row("THICK", {**row, "volume_ma_20": 2_000_000}) is not None


def test_unreadable_liquidity_fails_closed():
    """The filter exists for names where fills are the problem, so a name
    whose liquidity cannot be read is not given the benefit of the doubt."""
    assert scan_row("UNKNOWN", {"rsi_14": 18.0, "mfi_14": 30.0}) is None


def test_the_regime_filter_stays_off_for_this_setup():
    """The textbook rule is for trend-following. On washout-buying it
    INVERTED: the setup did better with the index below its 200-day average,
    consistently at 180, 200 and 220 days."""
    from sigbot.scan import REGIME_FILTER

    assert REGIME_FILTER is False
