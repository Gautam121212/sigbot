"""The F&O data reader — reads banked recorder output, never fetches."""
from __future__ import annotations

import json


def test_reads_banked_futures_rows(tmp_path):
    from sigbot.providers.futures_data import binance_futures, funding_history
    f = tmp_path / "bf.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in [
        {"ts": "2026-09-25T10:00:00+00:00", "symbol": "BTCUSDT", "funding_rate": 0.0001},
        {"ts": "2026-09-25T10:05:00+00:00", "symbol": "BTCUSDT", "funding_rate": 0.0003},
        {"ts": "2026-09-25T10:05:00+00:00", "symbol": "ETHUSDT", "funding_rate": -0.0002},
    ]))
    assert len(binance_futures(str(f))) == 3
    btc = funding_history("BTCUSDT", str(f))
    assert len(btc) == 2 and btc[0][1] == 0.0001


def test_missing_file_is_empty_not_an_error():
    from sigbot.providers.futures_data import binance_futures, has_enough
    assert binance_futures("data/does_not_exist.jsonl") == []
    assert has_enough("data/does_not_exist.jsonl") is False


def test_torn_last_line_is_skipped(tmp_path):
    from sigbot.providers.futures_data import binance_futures
    f = tmp_path / "bf.jsonl"
    f.write_text('{"ts":"t","symbol":"BTCUSDT","funding_rate":0.1}\n{"ts":"t2","sym')
    # the torn second line is skipped, the good one kept
    assert len(binance_futures(str(f))) == 1
