"""The backtest job must be honest about what a replay can and cannot show."""
from __future__ import annotations

from sigbot.backtest import BacktestResult
from sigbot.runner import _backtest_summary


def _result(symbol, n, acc, base, brier, baseline, signals=10):
    r = BacktestResult(symbol=symbol)
    r.n_predictions, r.n_signals = n, signals
    r.directional_accuracy, r.base_rate = acc, base
    r.brier, r.brier_baseline = brier, baseline
    return r


def test_an_edge_is_called_a_reason_to_test_not_proof():
    """A replayed result is a hypothesis about data the model may have been
    shaped on. Calling it proof is how a system starts lying about itself."""
    text = _backtest_summary(
        [_result("AAPL", 500, 0.56, 0.52, 0.240, 0.250)], [])
    assert "+4.0 points" in text or "Edge over base" in text
    assert "worth running forward" in text
    assert "not evidence that it works" in text


def test_no_edge_is_stated_plainly():
    text = _backtest_summary(
        [_result("AAPL", 500, 0.51, 0.52, 0.252, 0.250)], [])
    assert "Does not beat its baseline" in text


def test_the_accuracy_is_weighted_by_decision_count():
    """A symbol with ten decisions must not count as much as one with a
    thousand — unweighted averaging is how a thin, lucky symbol carries a
    pooled number."""
    text = _backtest_summary([
        _result("BIG", 1000, 0.52, 0.52, 0.250, 0.250),
        _result("TINY", 10, 0.90, 0.52, 0.100, 0.250),
    ], [])
    # Weighted: ~0.524. Unweighted would be 0.71.
    assert "52." in text and "71." not in text


def test_every_report_carries_its_caveats():
    """Survivorship, fitting on the same history, and replay-is-not-record."""
    text = _backtest_summary(
        [_result("AAPL", 500, 0.56, 0.52, 0.240, 0.250)], [])
    assert "delisted" in text
    assert "shaped on this same history" in text
    assert "nothing here is written to the ledger" in text


def test_no_decisions_blames_the_data_not_the_model():
    text = _backtest_summary([], ["A", "B", "C"])
    assert "no decisions" in text
    assert "result about the data" in text


def test_the_job_is_on_the_runner():
    import inspect

    import sigbot.runner as runner

    assert "backtest" in inspect.getsource(runner.main)
    assert callable(runner.run_backtest)
