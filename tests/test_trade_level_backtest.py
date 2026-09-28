"""Trade-level backtest — the honest V2 engine."""
from sigbot.trade_level_backtest import SUSTAINED_INFLECTION, describe, report


def test_real_trade_count():
    assert SUSTAINED_INFLECTION.total_trades == 1703


def test_positive_every_year_walk_forward():
    """The edge held out-of-sample in every year — real validation."""
    assert report().positive_every_year()


def test_net_is_below_gross_costs_modeled():
    s = SUSTAINED_INFLECTION
    assert s.avg_net_pct < s.avg_gross_pct        # costs actually subtracted


def test_tail_concentration_is_flagged():
    """The honest risk: some years are carried by a few winners."""
    tail_years = report().tail_concentrated_years()
    assert 2020 in tail_years                      # mean 11.65 vs median 0.40


def test_describe_is_honest_about_risk():
    out = describe()
    assert "NOT low-risk" in out
    assert "-87.4%" in out                          # worst trade shown
    assert "annual resolution" in out
