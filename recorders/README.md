# F&O data recorders

These bank live futures/options data so sigbot can later test edges that
price-only data can't reach. They run on YOUR machine (where the feeds are
reachable), append to `data/*.jsonl`, and sigbot reads those files.

**The key fact:** a backtest needs history, but these feeds only stream live.
So you run a recorder for days/weeks first; it accumulates the history; then the
edge campaign tests on it. Leave them running.

## 1. Binance crypto futures (funding rate + open interest)

No account, no key. Reachable from India.

```bash
python recorders/binance_futures_recorder.py --once   # test: one reading
python recorders/binance_futures_recorder.py          # leave running (5-min polls)
```

Banks the funding rate and open interest — the crowded-leverage edge.

## 2. Angel One Indian F&O (Nifty / Bank Nifty options + futures)

Free, but needs a free Angel One account + SmartAPI key (Indian resident).

```bash
pip install smartapi-python pyotp logzero websocket-client
export ANGEL_API_KEY=...  export ANGEL_CLIENT_CODE=...
export ANGEL_PIN=...      export ANGEL_TOTP_SECRET=...
python recorders/angelone_fno_recorder.py --once      # test
python recorders/angelone_fno_recorder.py             # leave running
```

Banks index option/future LTP, open interest, and volume — the Indian F&O
edges that match sigbot's NSE anchor.

## Running them in the background

```bash
nohup python recorders/binance_futures_recorder.py > data/binance.log 2>&1 &
nohup python recorders/angelone_fno_recorder.py > data/angel.log 2>&1 &
```

## When there's enough data

sigbot's reader (`sigbot/providers/futures_data.py`) reports when 200+ readings
are banked. At that point, tell me and I'll run the edge campaign on the banked
funding/OI history — pre-registered, across regimes, adopting only what survives.
