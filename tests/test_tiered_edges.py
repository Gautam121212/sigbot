"""Tiered edges — every model earns at multiple risk tiers."""
from sigbot.tiered_edges import MODELS, RISKY, STABLE, VERY_RISKY, describe


def test_every_model_has_risky_and_very_risky():
    for model, me in MODELS.items():
        assert me.has_all_tiers(), f"{model} missing risky/very-risky"


def test_stocks_have_all_three_tiers():
    tiers = {e.tier for e in MODELS["stocks"].edges}
    assert {STABLE, RISKY, VERY_RISKY} <= tiers


def test_ventures_now_has_a_stable_edge():
    stable = MODELS["ventures"].by_tier(STABLE)
    assert stable and "compounder" in stable[0].name


def test_news_has_a_short_signal_in_very_risky():
    vr = MODELS["news"].by_tier(VERY_RISKY)
    assert any("short" in e.name for e in vr)


def test_multiple_edges_per_tier_where_they_exist():
    # stocks has 3 stable edges (oversold, capitulation, pullback)
    assert len(MODELS["stocks"].by_tier(STABLE)) >= 3


def test_describe_covers_all_models():
    out = describe()
    for m in ("stocks", "crypto", "news", "ventures", "ideas"):
        assert m in out
