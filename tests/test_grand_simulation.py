"""Grand simulation — the consolidated per-model picture."""
from sigbot.grand_simulation import START, build_reports, describe


def test_every_model_is_reported():
    names = {r.name.split()[0] for r in build_reports()}
    assert {"STOCKS", "NEWS", "BLOWUP", "CRYPTO", "IDEAS/VENTURES"} <= names


def test_stocks_is_the_biggest_contributor():
    reps = {r.name.split()[0]: r for r in build_reports()}
    stocks_end = reps["STOCKS"].equity_curve[max(reps["STOCKS"].equity_curve)]
    news_end = reps["NEWS"].equity_curve[max(reps["NEWS"].equity_curve)]
    assert stocks_end > news_end             # stocks carries the system


def test_crypto_contributes_nothing_directional():
    reps = {r.name.split()[0]: r for r in build_reports()}
    assert not reps["CRYPTO"].equity_curve   # no curve — no direction edge


def test_ideas_ventures_flagged_as_under_fired():
    out = describe()
    assert "under-fire" in out or "below the 20" in out


def test_returns_are_realistic_not_fantasy():
    """No model should compound to fantasy millions on $100k."""
    for r in build_reports():
        if r.equity_curve:
            end = r.equity_curve[max(r.equity_curve)]
            assert end < START * 10          # never 10x+ from these edges
