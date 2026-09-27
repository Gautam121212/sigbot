"""Unified account — ONE $100k allocating across models (not $100k each)."""
from sigbot.unified_account import START, describe, run_unified


def test_one_account_grows_realistically():
    end, path, n_years = run_unified()
    assert end > START                     # it grows
    assert end < START * 10                # realistic, not fantasy millions
    assert n_years > 10                    # spans years


def test_the_account_is_one_not_per_model():
    """The whole point: start is ONE $100k split by the barbell, not $100k each."""
    end, path, _ = run_unified(start=100_000)
    # 5+ models but the account starts at 100k, not 500k
    assert path[0].equity < 200_000        # first year near the single start


def test_describe_states_single_account():
    out = describe()
    assert "ONE" in out and "not $100k each" in out
    assert "per year" in out


def test_cagr_is_professional_not_fantasy():
    end, path, n_years = run_unified()
    cagr = (end / START) ** (1 / n_years) - 1
    assert 0.03 < cagr < 0.30              # a believable professional range
