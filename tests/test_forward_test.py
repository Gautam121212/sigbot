"""Forward-test harness — separates real edges from survivorship mirages."""
from sigbot.forward_test import describe, forward_test


def test_a_signal_that_beats_baseline_survives():
    r = forward_test("good", fired=[3.0] * 100, baseline_all=[0.5] * 1000)
    assert r.survives and r.edge > 0.5


def test_a_signal_that_fails_forward_is_rejected():
    # the crypto turnover case: forward worse than baseline
    r = forward_test("turnover", fired=[-3.8] * 100, baseline_all=[-1.9] * 1000)
    assert not r.survives and "FAILS" in r.note


def test_too_few_cases_never_survives():
    r = forward_test("thin", fired=[10.0] * 10, baseline_all=[0.0] * 1000)
    assert not r.survives and "too few" in r.note


def test_describe_records_the_dead_edges():
    out = describe()
    assert "turnover" in out and "FAILS" in out
    assert "survivorship" in out
