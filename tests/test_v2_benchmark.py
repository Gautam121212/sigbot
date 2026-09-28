"""V2.0-BENCHMARK lock + sleeve-inclusion gate."""
from sigbot.v2_benchmark import BENCHMARK, describe, is_frozen, sleeve_adds_value


def test_benchmark_is_frozen():
    assert is_frozen()
    assert BENCHMARK.version == "V2.0-BENCHMARK"


def test_honest_forward_is_below_historical():
    """The benchmark records ~14% forward, not the lucky 21.9%."""
    assert BENCHMARK.cagr_forward < BENCHMARK.cagr_historical


def test_sleeve_gate_rewards_diversification_not_raw_cagr():
    """A 15% low-corr sleeve beats a 25% high-corr sleeve — the plan's rule."""
    assert sleeve_adds_value(15.0, 0.1)             # low corr, modest return: yes
    assert not sleeve_adds_value(25.0, 0.9)         # high corr, high return: no


def test_describe_states_the_lock():
    assert "LOCKED" in describe()
