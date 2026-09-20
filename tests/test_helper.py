"""The helper must be exact, or every fixture built on it is wrong."""
import pytest
from tests.conftest import write_records


@pytest.mark.parametrize("n,rate", [
    (20, 0.52), (30, 0.52), (60, 0.49), (140, 0.58), (150, 0.36),
    (160, 0.42), (210, 0.67), (100, 0.0), (100, 1.0), (7, 0.5),
])
def test_helper_produces_the_rate_it_claims(ledger, n, rate):
    got_n, wins = write_records(ledger, "news", f"S{n}{int(rate*100)}", n, rate)
    assert got_n == n
    assert abs(wins / n - rate) <= 0.5 / n, "rounding should be the only difference"


def test_helper_rejects_a_bad_rate(ledger):
    with pytest.raises(ValueError, match="not a proportion"):
        write_records(ledger, "news", "X", 10, 1.5)


def test_helper_catches_a_ledger_disagreement(ledger, monkeypatch):
    """If the ledger ever stopped agreeing, the helper must stop the test there."""
    real = ledger.resolve
    calls = {"n": 0}

    def flaky(pid, price, **kw):
        calls["n"] += 1
        return real(pid, 97.0 if calls["n"] % 2 else price, **kw)

    monkeypatch.setattr(ledger, "resolve", flaky)
    with pytest.raises(AssertionError, match="asked for"):
        write_records(ledger, "news", "Y", 40, 1.0)
