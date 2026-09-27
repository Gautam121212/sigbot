"""Full history run — one $100k across all models, honest accounting."""
from sigbot.full_history_run import START, describe, run


def test_the_account_grows_but_realistically():
    r = run()
    assert r.account_end > START
    assert r.account_end < START * 10       # realistic, not fantasy


def test_allocation_favors_the_best_model():
    """After the fix, ventures (best CAGR) should get more capital than a
    worthless model."""
    r = run()
    by_model = {m.model: m for m in r.per_model}
    # ventures started with more capital than crypto (weighted by return)
    assert by_model["ventures"].start > by_model["crypto"].start


def test_dead_weight_model_is_cut():
    """News at +2.5% CAGR is below the 3% floor -> allocated ~0."""
    r = run()
    by_model = {m.model: m for m in r.per_model}
    assert by_model["news"].start == 0


def test_it_reports_per_model_grows_and_loses():
    out = describe()
    assert "WHERE IT GROWS" in out
    assert "BENCHMARK GRADE" in out


def test_cagr_is_in_a_believable_range():
    r = run()
    cagr = (r.account_end / START) ** (1 / r.years) - 1
    assert 0.03 < cagr < 0.25               # honest, not fantasy
