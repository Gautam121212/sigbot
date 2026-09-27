"""Crypto movers, tier distribution, per-model run — the 3-part final run."""
from sigbot.crypto_movers import crypto_mover, is_loaded
from sigbot.per_model_run import START, run_model
from sigbot.tier_distribution import check_very_risky_holds_least, distribute


def test_crypto_coiled_and_loaded_fires():
    r = crypto_mover(range_10d=0.02, range_30d=0.04, volume_5d=2e6,
                     volume_20d=1e6, is_small_cap=True)
    assert is_loaded(r) and r.big_move_prob > 0.4
    assert r.tier == "very-risky"


def test_crypto_coiled_but_flat_volume_does_not_fire():
    r = crypto_mover(0.02, 0.04, 1e6, 1e6)
    assert not is_loaded(r)


def test_very_risky_holds_least_capital_every_model():
    for m, tiers in {"stocks": (True, True, True),
                     "crypto": (False, True, True)}.items():
        d = distribute(m, *tiers)
        assert check_very_risky_holds_least(d)
        assert d.weights.get("very-risky", 0) <= 0.10


def test_crypto_holds_cash_for_missing_stable():
    d = distribute("crypto", False, True, True)
    assert d.cash > 0 and "stable" not in d.weights


def test_every_model_runs_on_its_own_100k():
    for m in ("stocks", "news", "ventures", "crypto", "ideas"):
        p = run_model(m)
        assert p.end > 0
        assert p.years > 5


def test_no_model_is_fantasy():
    for m in ("stocks", "news", "ventures", "crypto", "ideas"):
        p = run_model(m)
        assert p.end < START * 10       # realistic
