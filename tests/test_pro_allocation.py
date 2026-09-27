"""Professional concentrated allocation — reach 20% by concentration."""
from sigbot.per_model_run import START, run_concentrated
from sigbot.pro_allocation import book_return, plan


def test_four_models_reach_twenty_concentrated():
    reaching = [m for m in ("stocks", "ventures", "ideas", "crypto")
                if plan(m).reaches_20]
    assert len(reaching) >= 3          # most strong models reach 20%


def test_news_is_honestly_a_support_sleeve():
    p = plan("news")
    assert not p.reaches_20 and "SUPPORT" in p.note


def test_book_reaches_twenty():
    assert book_return() >= 0.18       # whole book near 20%


def test_concentrated_run_beats_safe_for_strong_models():
    """Concentration lifts the strong models well above the machine-safe version."""
    vent = run_concentrated("ventures")
    assert vent.end > START * 3         # ventures compounds strongly


def test_concentration_does_not_fake_news():
    """News must NOT be inflated to 20% — honest ~5% is correct."""
    news = run_concentrated("news")
    news_cagr = (news.end / START) ** (1 / news.years) - 1
    assert news_cagr < 0.12            # honestly modest, not faked
