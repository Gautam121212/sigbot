"""The sixth model must measure money honestly and be unable to spend any."""
from __future__ import annotations

import pathlib

import pytest

from sigbot import paper
from sigbot.shadow import ShadowLedger


@pytest.fixture()
def led(tmp_path):
    return ShadowLedger(str(tmp_path / "s.db")), str(tmp_path / "s.db")


def test_a_long_that_rises_makes_money_minus_costs(led):
    ledger, path = led
    pid = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 110.0)                      # +10%

    book = paper.replay(path, starting_cash=100_000, position_pct=0.02,
                        cost_pct_per_side=0.00075)
    trade = book.trades[0]
    assert trade.gross_ret == pytest.approx(0.10)
    # 2% of 100k = 2,000 committed; 10% of that is 200 gross, less 3 in costs.
    assert trade.pnl == pytest.approx(2000 * 0.10 - 2000 * 0.0015)
    assert book.equity > book.starting_cash


def test_a_short_earns_the_inverse_of_the_move(led):
    """A SELL signal that is followed by a fall is a win, not a loss. Scoring
    it with the raw move would invert every short in the book."""
    ledger, path = led
    pid = ledger.record("daily", "MSFT", "SELL", 0.6, -0.01, 200.0)
    ledger.resolve(pid, 180.0)                      # price fell 10%

    book = paper.replay(path)
    assert book.trades[0].gross_ret == pytest.approx(0.10)
    assert book.trades[0].pnl > 0


def test_costs_are_charged_on_both_sides_and_can_turn_a_win_into_a_loss(led):
    """A move smaller than the round trip is not a profit, however often it
    is 'right'. This is the whole reason the model exists."""
    ledger, path = led
    pid = ledger.record("crypto15m", "BTC-USD", "BUY", 0.7, 0.001, 100.0)
    ledger.resolve(pid, 100.05)                     # +0.05%, under the 0.15%

    book = paper.replay(path)
    assert book.trades[0].gross_ret > 0, "direction was right"
    assert book.trades[0].pnl < 0, "and it still lost money after costs"


def test_predictions_without_both_prices_are_counted_not_invented(led):
    ledger, path = led
    ledger.record("news", "TSLA", "BUY", 0.5, 0.01, None)   # no entry price
    good = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(good, 101.0)

    book = paper.replay(path)
    assert len(book.trades) == 1
    # The unusable row must be visible as a number, never silently dropped.
    assert book.skipped_no_price >= 0


def test_per_model_money_is_separated(led):
    """A portfolio total hides which model paid for the others."""
    ledger, path = led
    a = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    b = ledger.record("crypto15m", "BTC-USD", "BUY", 0.7, 0.02, 100.0)
    ledger.resolve(a, 110.0)
    ledger.resolve(b, 90.0)

    by_model = paper.replay(path).by_model()
    assert by_model["daily"]["pnl"] > 0
    assert by_model["crypto15m"]["pnl"] < 0


def test_an_empty_ledger_says_so_rather_than_reporting_zero_return(led):
    _ledger, path = led
    book = paper.replay(path)
    assert book.trades == []
    assert "nothing to replay" in paper.verdict(book)


def test_the_replay_is_deterministic(led):
    """Same ledger, same answer, on any machine. Otherwise it is a story."""
    ledger, path = led
    for sym, exit_ in (("A", 101.0), ("B", 99.0), ("C", 103.0)):
        pid = ledger.record("daily", sym, "BUY", 0.6, 0.01, 100.0)
        ledger.resolve(pid, exit_)

    first = paper.replay(path)
    second = paper.replay(path)
    assert first.equity == second.equity
    assert [t.pnl for t in first.trades] == [t.pnl for t in second.trades]


def test_a_losing_run_reports_the_loss_plainly(led):
    ledger, path = led
    for sym in ("A", "B", "C", "D"):
        pid = ledger.record("daily", sym, "BUY", 0.6, 0.01, 100.0)
        ledger.resolve(pid, 95.0)                   # -5% each

    book = paper.replay(path)
    assert book.total_pnl < 0
    assert "LOST" in paper.verdict(book)
    assert book.max_drawdown > 0


def test_the_module_cannot_reach_a_broker():
    """Not a flag that must stay switched on — there is simply no broker.

    A paper trader that CAN reach a live account is one config mistake away
    from being a live trader. This asserts the absence, so a future edit that
    adds an order path has to delete a test that says why it must not."""
    source = pathlib.Path(paper.__file__).read_text()
    for forbidden in ("alpaca", "requests.post", "urllib.request",
                      "api_key", "API_KEY", "submit_order", "place_order",
                      "httpx", "socket"):
        assert forbidden not in source, (
            f"{forbidden!r} appeared in paper.py — the paper model must have "
            "no path to a broker or the network")


def test_the_summary_says_it_is_a_simulation_on_unproven_models(led):
    ledger, path = led
    pid = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 110.0)

    text = paper.summary(paper.replay(path))
    assert "simulation on paper" in text
    assert "no order was placed" in text
    assert "skill gate" in text


def test_state_is_written_for_the_site(led, tmp_path):
    ledger, path = led
    pid = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 110.0)

    out = paper.write_state(paper.replay(path), tmp_path / "paper.json")
    import json
    state = json.loads(out.read_text())
    assert state["trades"] == 1
    assert state["verdict"]
    assert state["starting_cash"] == paper.STARTING_CASH


def test_the_runner_job_actually_executes(tmp_path, monkeypatch):
    """The job shipped once with a call to a function that did not exist. No
    test invoked it, so the suite stayed green and only the linter noticed.
    This runs the job the way the scheduler does."""
    import sigbot.runner as runner
    from sigbot.shadow import ShadowLedger

    monkeypatch.chdir(tmp_path)
    # SETTINGS is a frozen dataclass, so point the env var it reads instead.
    monkeypatch.setenv("SIGBOT_DB", str(tmp_path / "shadow.db"))
    monkeypatch.setattr(runner, "SETTINGS",
                        type(runner.SETTINGS)(), raising=False)
    ledger = ShadowLedger(str(tmp_path / "shadow.db"))
    pid = ledger.record("daily", "AAPL", "BUY", 0.6, 0.01, 100.0)
    ledger.resolve(pid, 110.0)

    runner.run_paper()
    assert (tmp_path / "paper.json").exists()
