"""Trade-level reckoning — the honest per-model verdicts."""
from sigbot.trade_level_all_models import (
    ALL_STATS, IDEAS, describe, untradeable_models)


def test_ideas_is_flagged_untradeable():
    """The key finding: the raw Item-1.01 edge fails trade-level validation."""
    assert not IDEAS.tradeable
    assert "ideas" in untradeable_models()


def test_ideas_median_trade_loses_money():
    assert IDEAS.median_pct < 0                    # typical trade is a loss


def test_crypto_and_news_survive_as_tradeable():
    assert ALL_STATS["crypto"].tradeable
    assert ALL_STATS["news"].tradeable
    # both have positive median
    assert ALL_STATS["news"].median_pct > 0


def test_describe_is_honest_about_ideas():
    out = describe()
    assert "FALSE EDGE" in out
    assert "median trade loses money" in out


def test_ideas_live_runner_refuses_to_trade():
    """The safety gate: run_ideas_live records nothing while untradeable."""
    from sigbot.run_ideas_live import run_ideas_live
    result = run_ideas_live()
    assert "DISABLED" in result
