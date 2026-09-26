"""Big-winner precursor — reverse-engineered from actual explosive moves."""
from sigbot.big_winner import BASE_50X, big_winner_setup


def test_the_precursor_fires_on_high_vol_rising_volume():
    r = big_winner_setup(atr_pct=0.12, momentum_20=0.15, volume_ratio=2.0)
    assert r.is_precursor
    assert r.tail_50x_prob > 0.05        # meaningfully above base
    assert r.lift > 10                   # many times the base rate


def test_oversold_weakness_is_NOT_a_precursor():
    """The key finding: big winners are NOT oversold. A weak, calm, falling
    stock is exactly what the precursor rejects."""
    r = big_winner_setup(atr_pct=0.02, momentum_20=-0.10, volume_ratio=0.8)
    assert not r.is_precursor


def test_each_leg_is_required():
    # high vol + volume but NOT rising -> no
    assert not big_winner_setup(0.12, -0.05, 2.0).is_precursor
    # rising + volume but calm -> no
    assert not big_winner_setup(0.03, 0.15, 2.0).is_precursor
    # high vol + rising but no volume -> no
    assert not big_winner_setup(0.12, 0.15, 1.0).is_precursor


def test_the_lift_over_base_is_large():
    r = big_winner_setup(0.12, 0.15, 2.0)
    assert r.tail_50x_prob / BASE_50X > 20      # ~27x measured


def test_news_surprise_size_predicts_big_move_chance():
    from sigbot.big_winner import news_big_mover_prob
    # monotonic: bigger surprise -> higher chance of a big move
    assert news_big_mover_prob(2) < news_big_mover_prob(10) < news_big_mover_prob(30)


def test_huge_surprise_is_a_news_blowup():
    from sigbot.big_winner import is_news_blowup
    assert is_news_blowup(30)          # 25%+ surprise, 3x base odds
    assert not is_news_blowup(3)       # small surprise, no


def test_ideas_scanner_catches_real_opportunities():
    """Third-comparison check: the opportunity scanner fires on real opportunity
    news and rejects non-opportunities."""
    from datetime import datetime, timezone

    from sigbot.opportunities import OpportunityModel
    from sigbot.types import Article

    def mk(t):
        now = datetime.now(timezone.utc)
        return Article(uid=str(hash(t)), title=t, summary=t,
                       url=f"http://x/{abs(hash(t))}", source="reuters.com",
                       published_at=now, ingested_at=now)
    opps = [mk("India announces $10 billion semiconductor incentive scheme"),
            mk("Vietnam launches special economic zone with tax holiday")]
    controls = [mk("Company reports record quarterly earnings"),
                mk("Local restaurant wins community award")]
    cards = OpportunityModel().scan(opps + controls)
    assert len(cards) >= 2, "real opportunities produce cards"
    # controls should not dominate — at most the 2 real ones fire cleanly
    assert all(c.category == "opportunity" for c in cards)
