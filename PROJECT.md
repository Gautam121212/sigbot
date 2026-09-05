# Sigbot — the whole picture

Written to be read once, properly. Sections 1–3 are what it is. Section 4 is
what it has cost to get here. **Section 5 is what is still wrong**, and it is
the most useful part of this document.

Last updated after the adaptation layer landed. 8,931 lines of source, 4,621
lines of tests, 424 tests.

---

## 1. What this is

A research instrument that watches a rolling board of 100 assets, records a
prediction about each one every day, checks each prediction against what
actually happened, and reports the record.

It is **not** a price predictor and never was after the first week. It answers a
narrower question: *given what this asset and the things that move it have done
before, is there any measurable reason to pay attention today?* The output is a
suggestion with its evidence attached, not a forecast.

The distinction matters because it determines what can be verified. "NVDA will
rise 2% tomorrow" cannot be checked until tomorrow and is unfalsifiable in
advance. "AVGO followed a 2σ NVDA move 113 times out of 137 over 11.9 years" is
a fact about the past with an exact confidence interval, and no efficient-market
argument makes it wrong.

### The design constraint everything obeys

**A number may appear only if something measured it.** Every place a confident
figure could be produced without evidence is closed, and the closure is tested.
This is why:

- the app shows almost entirely amber for months
- most days produce no signal
- the report says SAMPLE DATA when it is showing sample data
- a claimed "8x return" is answered with a base rate, not a rating

---

## 2. How it works, end to end

```
    screener.py         picks the 100 from 156 candidates, on measurable
                        properties only
         |
    watchlist.py        holds the board, colours each asset from its own
                        record, replaces one or two at a time
         |
    runner.py daily     makes a prediction for every asset on the board
         |
    shadow.py           writes each prediction to the ledger, unresolved
         |
    runner.py resolve   24h later, scores each one against the price and
                        classifies why it failed
         |
    tiers.py            turns the record into a tier: SILENT, WATCH,
                        CAUTION, TRADE
         |
    adapt.py            reads the failure causes and changes one thing per
                        asset because of them
         |
    report.py           writes the page; setup_delivery.py sends the digest
```

### The models

| | Question | Backtestable | Publishes a score |
|---|---|---|---|
| **A — news** | Does this story move this asset? | No — no point-in-time archive | Not until the ledger earns one |
| **B — daily** | P(next close > today's)? | Yes | Yes, calibrated and lower-bounded |
| **C — contagion** | Anchor X shocked; which dependents react tomorrow? | Yes, validated both ways | Yes, from event-study frequencies |
| **D — opportunities** | IPOs, macro dislocations, business gaps | No — n=1 events | Never, by design |

Model C is the strongest idea here. Conditional prediction is a materially
easier problem than unconditional prediction, and it is the one with a working
null *and* power control.

### The screen: how an asset earns a board place

Seven criteria, all computed from history:

| | Start weight | Asks |
|---|---|---|
| stability | 18 | Does it behave the same across both halves of its history? |
| liquidity | 16 | Can you get in and out, without gaps? |
| movability | 16 | Do typical daily moves clear trading costs at all? |
| reactivity | 13 | Does it move more on event days than ordinary ones? |
| backtested | 13 | Does a walk-forward model find skill out-of-sample? |
| linkage | 12 | Does it follow any anchor with a next-day lag surviving FDR? |
| track_record | 12 | Once it has a live record, is that record any good? |

A screen score is **not** a forecast of profit. It says the asset is worth
spending checks on. That matters because every board slot takes months to build
a record, and spending one on something that barely trades is waste you would
not discover for a year.

Weights are re-learned from which criteria actually predicted good records —
but only above 25 assets with 60+ checks each, and never more than 2 points per
cycle.

### The colours

| | Meaning | Rule |
|---|---|---|
| **Green** | Ready to trade | 60+ checks, worst case clears 55% |
| **Amber** | Risky — watch only | too early, or measurable but weak |
| **Red** | Do not trade | 100+ checks, even the best case loses to a coin |

Rotation promotes on the **lower** bound and demotes on the **upper** bound.
That asymmetry is the whole defence against manufacturing survivorship bias: a
name is dropped only when even the most flattering reading of its record fails.

### Adaptation — the newest piece

The ledger always recorded *why* each miss happened. Nothing read it, so the
system could tell you what went wrong and make the identical assumption the next
day. `adapt.py` closes that:

```
AVGO: 100% of 55 misses were 'magnitude short'
  Right direction, move smaller than the cost of trading it.
  Hold longer.  Horizon 24h -> 36h.

MU: 100% of 55 misses were 'reversal'
  Reaches profit and gives it back.  Horizon 24h -> 16h.

SPY: 100% of 55 misses were 'gap against'
  Moves overnight, before there is any chance to act.
  Marked untradeable at this horizon.

DOGE-USD: 100% of 55 misses were 'direction wrong'
  No directional edge here. Marked for replacement.
```

Guards: 40+ misses required, one cause must be 40%+ of them, one change per
asset per 30 days, horizons clamped 6–72h. Every change stored with its
evidence.

---

## 3. Running it

```bash
cd ~/sigbot && source .venv/bin/activate

python -m sigbot.doctor                            # 15 checks, each with its fix
python scripts/run_screen.py --provider yahoo --apply   # 10-20 min, sets the board
python -m sigbot.runner daily                      # predict
python -m sigbot.runner resolve                    # score what came due
python -m sigbot.runner publish                    # rebuild the page
python -m sigbot.runner cycle                      # weekly: re-screen, rotate
python scripts/daily_digest.py                     # send the working state
```

Automation is `bash scripts/schedule.sh` (launchd, not cron — a job that misses
its slot because the Mac slept runs on wake; cron just skips the day).

**Location matters:** `~/sigbot`. macOS blocks background jobs from reading
`~/Downloads`, `~/Documents` and `~/Desktop`, and iCloud can offload a database
mid-write.

---

## 4. Every bug found, and what it cost

Kept because the pattern is more useful than any individual fix: **nearly every
one was invisible until something was tested against reality.**

| Bug | Consequence had it shipped |
|---|---|
| `hit` used gross return, `outcome_mode` used net | Every hit rate inflated by trades too small to cover costs |
| `run_daily` skipped HOLDs | 98 of 100 forecasts discarded daily; an asset needed **20 years** to reach a tier |
| Tests wrote `watchlist.db` into the project folder | A 20-minute screen silently discarded; the board came from a test fixture |
| Whole app built in JavaScript | Blank page on iPhone — Quick Look disables scripts |
| Isotonic calibration on a 150-row tail slice | 106 confident signals on pure noise, systematically losing |
| Asset-class cap had a backfill that defeated it | 7 crypto in a 10-slot board with a 50% cap |
| `pytest` missing from requirements | Setup step 5 could not work on any clean machine |
| Test helper computed 50.7% when asked for 38% | Five tests asserted on the wrong side of a threshold |
| 26 silently swallowed exceptions | A screen could run on 60% of the pool and look complete |
| `WebhookMessenger` accepted `file://` | A mistyped variable became a file read |
| Three orphan modules with passing tests | Green suite on code no entry point could reach |
| Doctor read "no predictions" on a clean all-hold day | A working system reported as broken |
| Stray-database check flagged the user's own data | Correct check that cried wolf |

Two rejected outright rather than fixed:

- **A gate that tightened +2% on a bad 20-trade window.** Simulated: it ratchets
  to its cap for a coin flip *and* for a genuinely skilled asset. It does not
  discriminate, it saturates.
- **A "40 observations, 60% gate" tier.** At an observed 70% rate, 40
  observations gives a 57.1% lower bound. The tier could only fire by moving its
  own gate down to meet it.

---

## 5. What is lacking

The honest section.

### The thing that decides whether any of this works

**No model has ever shown out-of-sample skill on real data.** The null controls
prove the instrument does not lie — they say nothing about whether an edge
exists. Every promising number so far is synthetic or historical.

The single unanswered question is whether `python scripts/run_contagion.py
--provider yahoo` finds any lagged link that survives FDR correction. If it
returns nothing, models B and C have no basis and the honest response is to
stop, not to loosen thresholds.

### Structural limitations that will not go away

- **Survivorship bias in the universe.** The pool is today's largest names,
  selected by having gone up. Fixing it needs historical index constituents.
- **`yfinance` adjusts prices retroactively** for splits and dividends. Old bars
  downloaded today are not what you saw then.
- **No point-in-time news archive.** Model A therefore has no backtest and
  cannot ever publish a probability from history. A real archive is five figures
  a year.
- **Residual calibration optimism.** Isotonic is fit on out-of-fold predictions
  and evaluated on the same set. Standard practice, mildly optimistic.

### Built but not wired

- **`adapt.py` computes per-asset horizons that `run_daily` does not read.** The
  diagnosis runs; nothing acts on it yet. Deliberate — watch its suggestions for
  a few weeks before letting it change behaviour.
- **`investment.py`, `confluence.py`, `microstructure.py`** are manual tools with
  no scheduled job. They work when called; nothing calls them.
- **News content never reaches the screen.** `reactivity` is a volume-spike
  proxy, not stories.
- **Intraday support exists but is unused.** `run_intraday` and 15m interval
  handling are there; nothing schedules them. This matters because daily-frequency
  lagged contagion is probably dead and intraday crypto is where it could live.

### Not built at all

- **Position sizing across the portfolio.** `expectancy.size_position` sizes one
  position. Twenty correlated longs on a risk-on day is one trade, not twenty,
  and nothing notices.
- **Execution.** No broker integration, no order management, no slippage model
  beyond a flat cost.
- **Real intraday validation.** Yahoo caps 15m history near 60 days, so an
  intraday strategy can only be validated forward.

### Timescales, honestly

With every forecast now recorded rather than only signals:

| | |
|---|---|
| An asset reaches WATCH (25 checks) | ~1 month |
| An asset reaches TRADE (150 checks) | ~5 months |
| Screen reweighting begins | ~2 months |
| Adaptation fires on an asset | 40+ misses, so ~2–4 months |

Before the HOLD fix these were 3.4 years, 20.5 years and 2.1 years. That single
bug made the stated timeline impossible.

### The largest risk, plainly

Not a bug. It is that a system this carefully built produces **nothing**, and
the care makes the emptiness feel like it must be hiding something. It is not.
If nothing ever goes green, the edge was not there — and learning that for the
cost of electricity is a good outcome, not a failed project.

The second-largest risk is the opposite: something goes green, you act on it,
and the green came from the one bias not yet closed. That is why the drop rule
uses the upper bound, why patterns are confirmed on a fresh sample, why the
class cap is hard, and why every rejected design in section 4 was rejected.

---

## 6. Verification

```
ruff (bug rules)          All checks passed
mypy                      Success: no issues found in 39 source files
bandit                    no unaddressed medium+ findings
tests                     424 passed, from a clean unpack
null control (Model B)    0 signals on 20 random walks
null + power (Model C)    2 planted links found, 32 spurious rejected
mutation checks           5 of 6 deliberate breaks caught; the sixth was a
                          redundant line, not a test gap
```

Everything touching the network — `YahooProvider`, `RSSProvider`, Telegram — has
only ever run against synthetic data in development. The skip ledger now reports
when those fail rather than swallowing it, so the first real problems will be
loud.
