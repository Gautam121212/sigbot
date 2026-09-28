"""Deep-decomposition edges for ventures and ideas (run 2)."""
from sigbot.deep_edges_2 import is_live, venture_inflection, volatile_catalyst


def test_volatile_smallcap_catalyst_is_live():
    r = volatile_catalyst(has_material_agreement=True, atr_pct=0.08,
                          market_cap=1e9)
    assert r.is_live_catalyst and is_live(r)
    assert r.big_move_prob > 0.1


def test_quiet_stock_catalyst_is_ignored():
    """The overlooked finding: a catalyst on a QUIET stock barely moves."""
    r = volatile_catalyst(True, atr_pct=0.02, market_cap=1e9)
    assert not r.is_live_catalyst and "quiet" in r.note


def test_large_cap_catalyst_is_not_live():
    r = volatile_catalyst(True, atr_pct=0.08, market_cap=1e10)
    assert not r.is_live_catalyst


def test_no_catalyst_no_signal():
    assert not volatile_catalyst(False, 0.08, 1e9).is_live_catalyst


def test_venture_inflection_needs_efficiency():
    """Sustained inflection AND positive ROIC = the venture edge."""
    good = venture_inflection([0.55, 0.58, 0.61, 0.64], [0.20, 0.28, 0.38],
                              roic=0.12)
    assert good.is_live_catalyst
    # same inflection but negative ROIC -> not the venture version
    bad = venture_inflection([0.55, 0.58, 0.61, 0.64], [0.20, 0.28, 0.38],
                             roic=-0.05)
    assert not bad.is_live_catalyst
