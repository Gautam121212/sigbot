"""Risky speculative bets — sized to magnitude, for stocks and crypto."""
from sigbot.risky_bets import direction_lean, evaluate_risky


def test_high_magnitude_plus_lean_produces_a_small_bet():
    lean = direction_lean(rsi=25, mom20=0.35)
    assert lean == "BUY"
    bet = evaluate_risky("SOL-USD", atr_pct=0.08, volume_ratio=3.0, rsi=25,
                         mom20=0.35, direction_lean=lean, crypto=True)
    assert bet is not None
    assert bet.side == "BUY"
    assert 0 < bet.size_pct <= 1.0          # small, capped
    assert bet.expected_move_pct > 6        # a meaningfully big potential move


def test_low_magnitude_is_no_bet():
    bet = evaluate_risky("AAPL", atr_pct=0.02, volume_ratio=1.0, rsi=50,
                         mom20=0.05, direction_lean=None)
    assert bet is None


def test_no_direction_lean_is_no_bet():
    # High magnitude but no lean (RSI neutral) -> no side to bet, no bet.
    bet = evaluate_risky("BTC-USD", atr_pct=0.08, volume_ratio=3.0, rsi=50,
                         mom20=0.35, direction_lean=None, crypto=True)
    assert bet is None


def test_overbought_leans_sell():
    assert direction_lean(rsi=75, mom20=0.1) == "SELL"


def test_crypto_baseline_is_higher_than_stocks():
    """Same flags, crypto expects a bigger move (it swings harder)."""
    c = evaluate_risky("BTC-USD", atr_pct=0.08, volume_ratio=3.0, rsi=25,
                       mom20=0.35, direction_lean="BUY", crypto=True)
    s = evaluate_risky("AAPL", atr_pct=0.08, volume_ratio=3.0, rsi=25,
                       mom20=0.35, direction_lean="BUY", crypto=False)
    assert c.expected_move_pct > s.expected_move_pct


def test_news_risky_bet_needs_a_big_surprise():
    from sigbot.risky_bets import news_risky_bet
    # small surprise -> no bet
    assert news_risky_bet("X", 3.0, "BUY") is None
    # big surprise + direction -> a bet sized to the move
    bet = news_risky_bet("NVDA", 45.0, "BUY")
    assert bet is not None and bet.side == "BUY"
    assert bet.expected_move_pct >= 7 and bet.size_pct <= 1.0


def test_news_magnitude_is_monotonic():
    from sigbot.risky_bets import news_magnitude
    assert news_magnitude(2) < news_magnitude(10) < news_magnitude(20) < news_magnitude(50)


def test_venture_needs_asymmetry_and_positive_ev():
    from sigbot.risky_bets import venture_risky_bet
    # capped downside + big upside + positive EV -> a bet
    bet = venture_risky_bet("Dubai property", 8.0, True, 1.5)
    assert bet is not None and bet.size_pct <= 1.0
    # uncapped downside -> no bet
    assert venture_risky_bet("risky", 8.0, False, 1.5) is None
    # small upside -> no bet
    assert venture_risky_bet("meh", 2.0, True, 1.5) is None
    # negative EV -> no bet
    assert venture_risky_bet("bad", 8.0, True, -0.5) is None


def test_idea_bet_only_when_fully_checked():
    from sigbot.risky_bets import idea_risky_bet
    assert idea_risky_bet("thesis", 3, 3) is not None      # all checks passed
    assert idea_risky_bet("thesis", 2, 3) is None          # incomplete
