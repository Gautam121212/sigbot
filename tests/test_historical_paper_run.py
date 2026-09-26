"""Historical paper run — proven models on $100k, realistic accounting."""
from sigbot.historical_paper_run import START, describe, run_all


def test_every_proven_model_runs():
    names = {r.name for r in run_all()}
    assert "stocks-capitulation" in names
    assert "stocks-pullback" in names
    assert "stocks-moonshot" in names
    assert "news-oversold-beat" in names


def test_no_model_compounds_to_fantasy():
    """Realistic caps: no single sleeve becomes tens of millions on $100k."""
    for r in run_all():
        assert r.end < START * 15         # capped, not fantasy


def test_a_positive_edge_grows_the_account():
    runs = {r.name: r for r in run_all()}
    assert runs["stocks-moonshot"].end > START


def test_describe_excludes_crypto_and_notes_backtest():
    out = describe()
    assert "Crypto: excluded" in out
    assert "BACKTEST" in out
    assert "crisis years" in out          # the capitulation honesty note


def test_pullback_has_the_measured_losing_years():
    from sigbot.historical_paper_run import PULLBACK
    # 2018 and 2022 were the two negative years (bear markets)
    assert PULLBACK[2018] < 0 and PULLBACK[2022] < 0
