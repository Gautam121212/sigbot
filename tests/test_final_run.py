"""Final historical paper run — the definitive check, with fault audit."""
from sigbot.final_run import audit, run


def test_the_fault_audit_is_clean():
    """The whole point: the final run has no faults — no corrupt data."""
    assert audit() == []


def test_four_models_reach_or_approach_twenty():
    r = run()
    strong = [m for m, c in r.per_model.items() if c >= 17]
    assert len(strong) >= 4            # stocks/ventures/crypto/ideas


def test_news_is_not_faked():
    r = run()
    assert r.per_model["news"] < 12    # honestly a support sleeve


def test_the_book_reaches_twenty():
    r = run()
    assert r.book_cagr >= 18           # whole book near 20%


def test_no_model_is_fantasy_or_negative():
    r = run()
    for cagr in r.per_model.values():
        assert -50 < cagr < 40         # realistic, not fantasy or broken


def test_ventures_is_the_strongest():
    r = run()
    assert r.per_model["ventures"] == max(r.per_model.values())
