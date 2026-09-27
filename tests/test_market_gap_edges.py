"""Market-gap edges — 2 per tier for stocks and ventures."""
from sigbot.market_gap_edges import (
    STOCK_EDGES, VENTURE_EDGES, describe, edges_by_tier)


def test_stocks_have_exactly_two_per_tier():
    for tier in ("stable", "risky", "very-risky"):
        assert len(edges_by_tier(STOCK_EDGES, tier)) == 2


def test_ventures_have_exactly_two_per_tier():
    for tier in ("stable", "risky", "very-risky"):
        assert len(edges_by_tier(VENTURE_EDGES, tier)) == 2


def test_tax_loss_bounce_is_a_stable_stock_edge():
    stable = edges_by_tier(STOCK_EDGES, "stable")
    assert any("tax-loss" in e.name for e in stable)


def test_margin_expansion_is_the_top_venture_edge():
    vr = edges_by_tier(VENTURE_EDGES, "very-risky")
    assert any("margin expansion" in e.name for e in vr)


def test_every_edge_names_its_mechanic():
    """The point: each edge explains WHY (the market gap), not just the number."""
    for e in STOCK_EDGES + VENTURE_EDGES:
        assert len(e.mechanic) > 10


def test_describe_shows_both_models():
    out = describe()
    assert "STOCKS" in out and "VENTURES" in out
    assert "why:" in out


def test_all_five_models_have_two_per_tier():
    from sigbot.market_gap_edges import (
        CRYPTO_EDGES, IDEA_EDGES, NEWS_EDGES)
    for edges in (CRYPTO_EDGES, NEWS_EDGES, IDEA_EDGES):
        for tier in ("stable", "risky", "very-risky"):
            assert len(edges_by_tier(edges, tier)) == 2


def test_news_short_signal_present():
    from sigbot.market_gap_edges import NEWS_EDGES
    vr = edges_by_tier(NEWS_EDGES, "very-risky")
    assert any("SHORT" in e.name for e in vr)


def test_crypto_small_cap_edges_in_very_risky():
    from sigbot.market_gap_edges import CRYPTO_EDGES
    vr = edges_by_tier(CRYPTO_EDGES, "very-risky")
    assert any("turnover" in e.name for e in vr)
    assert any("ignition" in e.name for e in vr)


def test_describe_shows_all_five_models():
    out = describe()
    for m in ("STOCKS", "VENTURES", "CRYPTO", "NEWS", "IDEAS"):
        assert m in out
