"""The live scan must record every signal and act on only what risk allows.

This is the path B36, B52 and B68 all burned: conflating "record" with "act".
A signal refused on risk grounds is still evidence about the setup, and
dropping it would make the risk rules invisible in the record they distort.
"""
from __future__ import annotations

import inspect

import sigbot.runner as runner


def test_the_scan_records_before_risk_can_refuse():
    src = inspect.getsource(runner.run_stocks)
    record_at = src.index('ledger.record("stocks"')
    # The only place a signal is dropped from `hits` is after recording.
    append_at = src.index("hits.append(hit)")
    assert record_at < append_at, (
        "every firing signal must be written down before risk decides "
        "whether it can be afforded")


def test_the_scan_builds_an_exit_plan_before_sizing():
    """Sizing comes from the stop distance, so the plan must exist first."""
    src = inspect.getsource(runner.run_stocks)
    assert src.index("exit_plan(") < src.index("decide(")
    assert "stop_price=plan.stop_price" in src


def test_risk_state_accumulates_within_the_run():
    """Checking each signal against an empty book would make every limit
    vacuous — a thirty-signal day would take all thirty."""
    src = inspect.getsource(runner.run_stocks)
    assert "sector_positions=sector_count.get(sector, 0)" in src
    assert "open_positions=state.open_positions + 1" in src
    assert "deployed=state.deployed + decision.size" in src


def test_refused_signals_stay_visible():
    src = inspect.getsource(runner.run_stocks)
    assert "recorded=len(hits) + len(refused)" in src, (
        "the run log must count recorded signals, not just taken ones — the "
        "gap between them IS the risk rules working")


def test_a_signal_without_volatility_is_never_traded():
    """No volatility reading means no stop, which means unknown risk."""
    src = inspect.getsource(runner.run_stocks)
    assert "if plan is None:" in src
    assert "no volatility reading" in src


def test_the_site_draws_the_board_not_the_whole_pool():
    """Removing the 100-name ceiling from the models also removed it from the
    page: 606 charts and a page that grew from about 2 MB to 17 MB."""
    import inspect

    from sigbot.runner import board_assets, display_assets

    assert len(display_assets()) < len(board_assets())
    src = inspect.getsource(runner.run_publish)
    assert "display_assets(settings)" in src and "board_assets(settings)" not in src


def test_publish_is_tracked_not_a_helper_inside_it():
    """The tracker reset failure counts mid-run while publish itself was
    untracked and carried stale counts between runs."""
    import inspect

    src = inspect.getsource(runner)
    assert '@_tracked("publish")\ndef run_publish(' in src
    assert '@_tracked("publish")\ndef _report_fingerprint(' not in src
