"""Business ventures judged by asymmetry — risky-but-survivable bets pass."""
from __future__ import annotations

from sigbot.ventures import (
    MAX_VENTURE_RISK, Venture, evaluate, size_bet,
)


def _v(upside, p, ev_strength=0.4, capped=True):
    return Venture("t", "thesis", upside, p, ev_strength, capped)


def test_a_risky_but_survivable_asymmetric_bet_is_worth_taking():
    """Thin evidence, long odds — but capped downside and big upside. This is
    the case the whole model exists for, and the 'brutal gates' must let it
    through."""
    factory = _v(upside=6.0, p=0.30, ev_strength=0.35)     # +1.1x EV
    assert factory.risky, "thin evidence and long odds -> labelled risky"
    assert factory.worth_taking, "but capped + asymmetric -> taken, small"
    assert factory.verdict().startswith("WORTH A SMALL BET")
    assert "(RISKY)" in factory.verdict()


def test_uncapped_downside_is_never_worth_taking_however_big_the_upside():
    """The one rule the barbell never breaks: an unbounded loss ends the game."""
    moonshot = _v(upside=50.0, p=0.40, capped=False)
    assert not moonshot.worth_taking
    assert moonshot.verdict() == "AVOID — downside not bounded"
    assert any("UNCAPPED" in r for r in moonshot.risk_reasons())


def test_a_small_upside_does_not_justify_the_uncertainty():
    weak = _v(upside=2.0, p=0.45)      # below the asymmetry floor
    assert not weak.worth_taking
    assert weak.verdict().startswith("PASS")


def test_negative_expected_value_is_passed_even_with_a_big_upside():
    lottery = _v(upside=12.0, p=0.05)      # EV below 1.05x
    assert not lottery.worth_taking


def test_stake_is_always_survivable():
    """No bet risks more than the capped fraction of capital, and thin evidence
    shrinks it further — so a total loss is a scratch."""
    strong = _v(upside=8.0, p=0.4, ev_strength=1.0)
    thin = _v(upside=8.0, p=0.4, ev_strength=0.3)
    assert size_bet(100_000, strong) <= 100_000 * MAX_VENTURE_RISK + 1e-6
    assert size_bet(100_000, thin) < size_bet(100_000, strong)
    assert size_bet(100_000, _v(upside=2.0, p=0.4)) == 0.0, "not taken, not sized"


def test_ventures_sort_best_asymmetry_first_and_keep_the_risky_ones():
    vs = evaluate([_v(upside=2.0, p=0.4), _v(upside=6.0, p=0.3, ev_strength=0.35),
                   _v(upside=50.0, p=0.4, capped=False)])
    assert vs[0].worth_taking, "the worth-taking bet ranks first"
    # The risky and the avoid bets are still present — never dropped.
    assert len(vs) == 3
