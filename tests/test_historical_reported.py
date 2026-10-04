"""HISTORICAL_REPORTED — unreproducible results excluded from qualification."""
from sigbot.canonical_evidence import (
    EvidenceState, build_canonical_store)


def test_historical_reported_does_not_count():
    assert not EvidenceState.HISTORICAL_REPORTED.counts_for_qualification()


def test_backtest_still_counts():
    assert EvidenceState.BACKTEST.counts_for_qualification()


def test_paper_and_live_count():
    assert EvidenceState.PAPER.counts_for_qualification()
    assert EvidenceState.LIVE.counts_for_qualification()


def test_inflection_facts_are_historical_reported():
    store = build_canonical_store()
    for key in ("inflection.trades", "inflection.net_per_trade",
                "inflection.win_rate", "inflection.sharpe",
                "inflection.forward_cagr", "inflection.walk_forward"):
        f = store.get(key)
        assert f is not None, key
        assert f.state == EvidenceState.HISTORICAL_REPORTED, \
            f"{key} is {f.state.value}, must be historical_reported"


def test_no_inflection_fact_counts_for_qualification():
    """The 1,703 result and all its derivatives must be structurally excluded
    from unlocking capital/sizing/qualification."""
    store = build_canonical_store()
    for key in store.all_keys():
        if key.startswith("inflection."):
            f = store.get(key)
            assert not f.state.counts_for_qualification(), \
                f"{key} still counts for qualification"


def test_historical_reported_is_weakest():
    from sigbot.canonical_evidence import _STRENGTH
    hr = _STRENGTH[EvidenceState.HISTORICAL_REPORTED]
    assert hr < _STRENGTH[EvidenceState.BACKTEST]
    assert hr == min(_STRENGTH.values())
