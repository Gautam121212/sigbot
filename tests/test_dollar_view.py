"""Dollar view — model returns on $100k, clean trades only."""
from sigbot.dollar_view import STAKE, model_money
from sigbot.shadow import ShadowLedger


def test_dollar_per_trade_reflects_the_stake(tmp_path):
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    # 30 trades, each +2% realised
    for i in range(30):
        pid = led.record("stocks", f"S{i}", "BUY", 0.6, 0.02, 100.0)
        led.resolve(pid, 102.0)     # +2%
    money = {m.model: m for m in model_money(db)}
    assert "stocks" in money
    # +2% on a $2000 stake = +$40/trade
    assert abs(money["stocks"].dollar_per_trade - STAKE * 0.02) < 5


def test_corrupt_rows_excluded_from_money(tmp_path):
    db = str(tmp_path / "s.db")
    led = ShadowLedger(db)
    for i in range(25):
        pid = led.record("crypto15m", f"C{i}", "BUY", 0.6, 0.02, 100.0)
        led.resolve(pid, 101.0)
    # one corrupt +90% row must not inflate the money
    bad = led.record("crypto15m", "BAD", "BUY", 0.6, 0.02, 1.0)
    led.resolve(bad, 1.9)           # +90%
    money = {m.model: m for m in model_money(db)}
    # the corrupt row is excluded (ABS(ret) <= 0.5), so per-trade stays small
    assert money["crypto15m"].dollar_per_trade < STAKE * 0.1
