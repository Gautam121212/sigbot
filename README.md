# sigbot

Four signal models over a 20-asset anchor universe, a walk-forward backtester,
an FDR-controlled network screener, a forward-scoring ledger, and vendor-neutral
message delivery.

Design principle throughout: **a number is only allowed on screen if something
measured it.** Every path that could print a confident-looking score without
evidence is gated shut, and the gates are tested.

---

## The four models

| | Question | Backtestable | Publishes a score |
|---|---|---|---|
| **A — news** `news_model.py` | Does this story move this asset? | **No** — no point-in-time archive | Not until the ledger earns one |
| **B — daily** `daily_model.py` | P(next close > today's close)? | Yes | Yes, calibrated + lower-bounded |
| **C — contagion** `contagion.py` | Anchor X shocked. Which dependents react tomorrow? | **Yes, validated both ways** | Yes, from event-study frequencies |
| **D — opportunities** `opportunities.py` | IPOs, macro dislocations worth a look | **No** — n=1 events | **Never.** By design |

Model C is the strongest idea of the four. Conditional prediction ("given NVDA
just moved 3σ, what does AVGO do tomorrow") is a materially easier problem than
unconditional prediction, which is why it deserves more of your attention than
Model B.

---

## Model C, and the two things that kill it

**Contemporaneous versus lagged.** The screener measures both, separately:

- *same-day beta* — the dependent moves the same day as the anchor. Large,
  obvious, and worth nothing: by the time you see the anchor move, the
  dependent has already moved.
- *next-day beta* — the only one you can act on.

For liquid US large caps at daily frequency the lagged term is usually
indistinguishable from zero. The screener is built to say so rather than to
find something.

**Multiple testing.** 20 anchors × 72 candidates is 1,440 hypotheses. At
p<0.05 you get ~72 false discoveries from luck alone. Benjamini-Hochberg FDR
control is applied across the *whole* screen, not per anchor.

### Control run

`scripts/run_contagion.py --provider synthetic` plants two known lag-1
relationships (beta 0.35 and 0.20) inside 48 unrelated series and runs the real
screener over all of it:

```
SCREEN: 500 pairs tested, target FDR 10%
  uncorrected p<0.05 would report   32
  surviving Benjamini-Hochberg      2

D ~ A0: same-day beta +0.00, next-day beta +0.376 (t=+20.40, q=0.000, n=2998)
    D after a 2σ A0 move: next-day +1.87% (10–90% -0.31% to +4.00%),
    direction 82% vs base 60%, n=137  -> would alert

E ~ A1: same-day beta +0.01, next-day beta +0.202 (t=+11.17, q=0.000, n=2998)
    E after a 2σ A1 move: next-day +0.70% (10–90% -1.46% to +2.76%),
    direction 65% vs base 56%, n=135  -> would alert
```

Both planted links recovered with the right betas, 32 spurious links rejected,
zero false positives. Validated in **both** directions — power and null. A
screener tested only against noise passes by returning nothing.

---

## Model B, and the bug its null control caught

`scripts/run_backtest.py --provider synthetic` runs the whole daily pipeline
over 20 random walks. There is no signal in that data; anything found is a bug.

The first version failed:

```
signals fired          106  (0.15% of days)
signal hit rate        0.349   95% CI [0.265, 0.444]
t-stat                 -2.35
```

106 confident signals on pure noise, systematically losing. Cause: isotonic
calibration fit on a single 150-row tail slice — enough to manufacture a
convincing reliability bin out of nothing. Fixed with pooled out-of-fold
calibration and a **model-level skill gate**: a model that has not demonstrated
positive out-of-fold Brier skill may not trade at all, however extreme any one
prediction looks.

```
signals fired          11   (0.02% of days)
signal hit rate        0.455   95% CI [0.213, 0.720]
t-stat                 0.00
mean Brier skill       -0.00408
mean ECE               0.0376   (was 0.0695)
```

Indistinguishable from chance, which is correct. A test asserts this.

---

## Model D emits no score, deliberately

A score has to come from somewhere. Models B and C get theirs from thousands of
resolved observations. Model D cannot:

- IPOs are ~200–300 a year, each structurally unique, and the "growth plans"
  you would score are written by people paid to make them sound good.
- Macro theses ("property is cheap in X because of conflict") are n=1. There is
  no population to compute a frequency over. "80% confidence" on one would be a
  number with no denominator.

So it emits a **thesis card**: the claim, the mechanism, what must be true, what
would falsify it, and what you cannot currently observe. The point is to make a
weak idea look weak on the page. `opportunities.SCORING_REQUIREMENTS` lists what
data would make it scoreable — an acquisition problem, not a modelling one.

Digests carry a jurisdiction note. Operating from India, LRS remittance limits,
TCS on foreign remittance, flat-rate VDA taxation with TDS, and FEMA
restrictions on direct overseas property purchase all bear on whether anything
in the digest is actionable at all. Verify current rules with a qualified
advisor — the note is a prompt to check, not advice.

---

## On trusting the test suite

A green suite proves the code matches the tests. It does not prove the tests say
the right thing — and in this project a fixture bug proved that the hard way.
Five test files each wrote ledger records with their own win-rate logic, and
several used `(i % 100) / 100 < rate`, which does not produce the rate it claims:

```
asked for 58% over 140 records -> actually 70.0%
asked for 49% over  60 records -> actually 81.7%
asked for 52% over  20 records -> actually 100.0%
```

Those tests passed. Their assertions were loose enough to survive a fixture that
meant something different from what it said, which is the worse failure — a
green suite then tells you nothing about the case you thought you were testing.

**The fix is one helper instead of five, and one that checks its own output.**
`tests/conftest.py` writes exactly `round(n * rate)` wins and then asserts the
ledger agrees before handing back. A fixture that silently produces the wrong
thing is the one bug a test suite cannot catch for you. `tests/test_helper.py`
verifies the helper across ten (n, rate) pairs and confirms it raises when the
ledger disagrees.

Two files were deliberately left alone: `test_tiers.py` and `test_core.py` write
specific OHLC to test outcome classification, and routing them through a
rate-based helper would lose the point.

### Silent failures

The most dangerous pattern in the codebase was not a bug — it was 26 places that
caught an exception and moved on without a word:

```
screen 156 candidates, 40 fail to load, see 116 results
```

Nothing told you a quarter of the pool never ran. You got a smaller answer that
looked exactly as confident as a complete one. A crash would have been safer,
because a crash tells you to look.

`skips.py` counts what was skipped and why, and the count appears alongside the
result:

```
Screened 12 candidates: 12 usable, 0 rejected outright.
8 of 20 could not be processed (ValueError 8) — this ran on 60% of the
intended set.
```

The exception is still caught — one bad symbol should not stop a scan of a
hundred and fifty. What changed is that the scan says so. Counts are scoped per
run, so this morning's failure does not make tonight's run look broken, and
deduplicated per item: a symbol that fails computing returns and again when
scored is one skipped asset, not two. That double-count reported "16 of 28" for
eight broken symbols out of twenty, which is a wrong number stated confidently —
exactly what the module exists to prevent.

`require_coverage()` raises where a partial answer would mislead rather than
merely be incomplete. A contagion screen over a third of the anchors is not a
weaker version of the real screen; it is a different one.

A broken board now says it is broken instead of rendering as empty. Those look
identical on screen and mean opposite things.

`ruff --select S110,S112` is clean: **zero silent swallows remain.**

### Static analysis and dead code

A full audit pass found and fixed, with no change to behaviour:

| Found | Count |
|---|---|
| unused imports and dead assignments | 9 |
| a discarded blocking reason (a contagion link vanished silently) | 1 |
| a match object reached back into after its branch (crash waiting to happen) | 1 |
| `datetime(*tuple)` with no length check | 1 |
| a name reused for two different types in one function | 1 |
| `_mean` computed twice per field, once to test and once to round | 3 |
| **orphan modules: whole parallel implementations that shipped but were never called** | **3** |

The orphans are the ones worth naming. `screen.py` duplicated `screener.py`,
`sensitivity.py` duplicated `recurrence.py`, and `build_static.py` was a second
static renderer alongside `report.py`. Each had passing tests, so the suite was
green on code that no entry point could reach — and two implementations of the
same page are how one silently drifts from the other. Roughly 29 KB removed; the
shipping renderer already had equivalent coverage for scripts, escaping and the
empty state.

`ruff` and `mypy` both run clean across 36 source files.

### Mutation checks

Tests were broken on purpose to confirm they catch what they claim to:

| Break | Caught by |
|---|---|
| drop threshold 100 → 10 checks | 1 test |
| Wilson bound returns the point estimate | 5 tests |
| a `<script>` tag back in the report | 2 tests |
| screen learns from 2 assets instead of 25 | 2 tests |
| discovery stats quoted after promotion | 1 test |

One mutation was **not** caught: removing the counter reset on promotion. That
turned out to be a redundant line rather than a test gap — during discovery those
counters are never incremented, so they are already zero. The real defence is
which stats get quoted, and mutating that does fail a test.

## Setup

**New to this? Read [SETUP.md](SETUP.md) instead** — same steps, written for
someone who has not used Terminal before, with a troubleshooting table and an
honest account of what the first few months look like.

## Setup (short version)

```bash
pip install -r requirements.txt
python -m pytest tests -q                             # 182 tests, ~110s, no network
python scripts/run_backtest.py  --provider synthetic   # Model B null control
python scripts/run_contagion.py --provider synthetic   # Model C null + power control
python scripts/run_backtest.py  --provider yahoo       # real data
python scripts/run_contagion.py --provider yahoo       # real data
```

Cron:

```
30 22 * * 1-5  python -m sigbot.runner daily
0  */4 * * *   python -m sigbot.runner news
0  21 * * *    python -m sigbot.runner contagion
0  8  * * *    python -m sigbot.runner opportunities
0  23 * * *    python -m sigbot.runner cycle
0  4  * * 0    python -m sigbot.runner cycle --rescreen
0  9  * * 1    python -m sigbot.runner cycle      # resolve, re-screen, rotate
30 9  * * 1    python -m sigbot.runner publish    # chart the board, rebuild the app
0  10 * * 1    python -m sigbot.runner report
```

Delivery is a generic HTTP POST, so any provider works without a code change:

```bash
export SIGBOT_WEBHOOK_URL="https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>"
```

Console and file sinks always run, so nothing is lost if the webhook fails.
Credentials live in the environment only.

---

## Alert tiers (evidence-based, not time-based)

Tier is a property of the resolved track record, not of how long the bot has
been running. An asset with 200 observations on day 40 outranks one with 12 on
day 400. No code path can promote an asset early or lower a floor to reach one.

| Tier | Requires | Meaning |
|---|---|---|
| SILENT | anything less | collecting; no alert |
| WATCH | n >= 25 and 90% lower bound >= 0.50 | weak evidence, paper only |
| CAUTION | n >= 60 and lower bound >= 0.55 | building, reduced size |
| TRADE | n >= 150 and lower bound >= 0.60 | evidenced |

The floors are derived, not chosen. At 90% confidence an observed 65% hit rate
needs n>=27 to clear a 50% floor, n>=61 for 55%, and n>=244 for 60%. This is
why a "40 observations, 60% gate" tier cannot exist: 40 observations at an
observed *70%* rate gives a lower bound of 57.1%. Such a tier can only fire by
moving its own gate down to meet the evidence.

### Outcome classification

Resolved predictions are classified from the outcome bar into `win`,
`magnitude_short`, `direction_wrong`, `reversal`, `gap_against`, or
`unexplained`. Every one is derivable from OHLC.

Categories like "news conflict", "low liquidity" and "random" are deliberately
absent. They cannot be distinguished from price data, so logging them would
record a guess and then treat the guess as evidence. Anything the price path
cannot explain is `unexplained`, and a rising `unexplained` count means the
model has no edge here — not that it needs another category.

### What is NOT implemented, and why

An auto-adjusting gate (tighten +2% when a 20-prediction window reads below
50%, loosen -1% above 65%) was proposed and rejected after simulation. With a
20-observation window the standard error on a hit rate near 0.5 is ~11%, so:

```
true 55%: P(window reads <50% -> TIGHTEN) = 24.8%   P(reads >65% -> LOOSEN) = 13.1%
true 65%: P(window reads <50% -> TIGHTEN) =  5.3%   P(reads >65% -> LOOSEN) = 41.7%
```

Over 400 predictions the asymmetric step (+2% vs -1%) ratchets the gate to its
cap regardless of quality — median final gate 0.94 for a genuinely skilled 55%
asset and 0.95 for a coin flip. It does not discriminate; it saturates. Worse,
a gate that loosens to let a signal through converts an honest HOLD into an
"ALL GATES PASS" label, which is the exact failure the gate exists to prevent.

## Pattern registry: discovery, pruning, confirmation

`patterns.py` implements test-many-prune-most, with one correction.

**What works in that strategy.** Simulating 400 patterns per campaign through
prune-at-20 and promote-at-100 with a 0.65 Wilson floor, 40 campaigns: across
16,000 pure-noise pattern-runs, **not one reached TRADE**. False discovery is
not the failure mode.

**What breaks.** The *reported number*:

```
population                        promoted/campaign  reported  true    bias
400 pure noise (true 50%)                      0.0      —       —       —
380 noise + 20 real (true 62%)                 0.8    72.5%   62.0%  +10.5pp
380 noise + 20 strong (true 70%)              14.8    73.1%   70.0%   +3.1pp
```

A pattern crosses the floor on a favourable run, and the statistic is measured
on the same data that selected it. **A 62%-true system reports 70%.** That is
the number you would act on.

**The fix — two stages with a hard reset:**

| Stage | Rule | What may be quoted |
|---|---|---|
| DISCOVERY | prune at n>=20 if rate<45%; promote at n>=100 with lower>=0.65 | discovery rate, labelled optimistic |
| CONFIRMING | counters **zeroed** on promotion; fresh sample only | fresh rate, marked incomplete |
| CONFIRMED | n>=60 with lower>=0.50 on the fresh sample | the fresh rate |
| PRUNED | permanent; cannot revive | nothing |

Confirmation gate chosen by simulation (pass rate at n>=60, lower>=0.50):
true 50% -> 4.4%, true 55% -> 18.4%, true 62% -> 58.1%, true 70% -> 93.6%.

Residual bias is stated rather than hidden: the confirmation gate is itself a
filter, so looking only at CONFIRMED patterns reintroduces ~1-2pp of upward
conditioning. Down from +10.5pp, not zero.

**Idempotent recording.** `record()` keys on an `observation_id` that must
identify the *event* (a bar timestamp), not the moment the collector ran. A
collector re-reading the last three shocks every four hours would otherwise log
them six times a day and manufacture exactly the sample size that gates
promotion. A test replays six runs over three shocks and asserts n stays at 3.

**What the 0.65 floor costs.** A true 62% edge is real and tradeable, and this
pipeline discards it most of the time (40 campaigns at true 62%: <=10 confirmed).
Deliberate — false confidence costs more than a missed pattern — but it means
"3-5 patterns at 65-75%" requires patterns whose TRUE rate is near 70%.

### How long 100 observations actually takes

```
daily contagion, one pair at 2 sigma      120.0 months to n=100
daily news alert, one asset                48.0 months to n=100
15m crypto contagion, one pair at 2 sigma   1.1 months to n=100
```

Only the intraday crypto channel can reach a TRADE-tier sample inside a year.
Any timeline promising TRADE-tier patterns in month 4 is describing that channel
alone. And Yahoo caps 15m history near 60 days, so intraday patterns can only be
validated **forward** — there is no intraday backtest to shortcut it with.

## Microstructure signals: attestation before edge

`microstructure.py` refuses to let a claimed edge attach to a detector that
does not observe the mechanism producing it.

| claimed mechanism | detector proposed | observes it? |
|---|---|---|
| post-earnings drift | gap >3% on >2.5x volume | **NO** — no earnings calendar |
| perpetual funding extreme | RSI > 85 + volume spike | **NO** — RSI is a price oscillator, not funding |
| index inclusion forced bid | volume spike + near 52wk high | **NO** — inclusions are announced, not inferred |
| VIX spike reversion | VIX > 35 and > 2x 20d avg | yes |
| macro first-bar momentum | first 5m bar after 13:30 UTC | partial — needs a release calendar |

Three of five detectors measure something other than the mechanism. Their
claimed hit rates belong to different signals. `SignalSpec` raises if a
`claimed_hit_rate` is set without a `claim_source`, and no spec in `SPECS`
carries one — none of the figures offered (72%, 78%, 76%, 77%, 71%, with event
counts) came with a citation.

**PEAD is not a 30–60 minute effect.** It is a multi-month drift in
cross-sectional abnormal returns, and it has attenuated — hedge returns fell
from roughly 5% per quarter in the 1980s–90s to about 4% in the 2000s and 3% or
lower by the late 2010s. An intraday reading of PEAD is a different claim with
no cited support behind it.

**A signal blocked by its own regime filter is an error, not a feature.** The
proposed design blocks all signals when VIX > 35 and defines a signal that
fires only when VIX > 35. `validate_signal_set` raises instead of shipping a
signal that silently never fires while still appearing in the strategy table.

## Confluence: independence is the whole lift

Requiring two signals to agree helps in proportion to how independent they are:

```
    p     rho    P(correct|agree)   agreement rate
  0.72   0.00              86.9%            59.7%
  0.72   0.30              80.7%            71.8%
  0.72   0.60              76.2%            83.9%
  0.72   0.80              73.9%            91.9%
  0.72   0.95              72.5%            98.0%
```

At rho=0.8 the lift is 1.9 points, not 15 — and correlated signals agree 92% of
the time, so the "confluence required" filter barely filters. A gap+volume
detector, an RSI+volume detector and a volume+52-week-high detector all key off
the same volume spike on the same bar. Their agreement is one observation
counted three times.

`confluence.py` therefore **measures** rho from resolved history rather than
assuming independence, refuses to claim any lift on fewer than 40 paired
events, and prefers the directly observed agreement hit rate over the analytic
posterior whenever enough co-occurring events exist.

## ORB: the one strategy, backtested

`orb.py` is the whole opening-range-breakout strategy in one file, with a CLI:

```bash
python scripts/run_orb.py --provider synthetic       # null control, offline
python scripts/run_orb.py --symbol SPY --days 59     # real data
python scripts/run_orb.py --csv my_15m_bars.csv      # any other source
```

### The null control, and the tuning trap it exposes

Run on 250 days of driftless intraday bars — data with no breakout structure:

```
trades 81
win rate 38.3%  (90% lower bound 29.9%)
mean -0.038R   total -3.1R   t-stat -0.29
```

Correct: a 1.5R target on a random walk wins near 40% and earns nothing. But
look at the parameter surface on that same structureless data:

```
 volume_multiple  target_r    n  win_rate  mean_r  total_r
           1.250     1.000  107     0.505   0.019    2.045
           1.250     1.500  107     0.402   0.003    0.317
           1.250     2.000  107     0.355   0.031    3.351     <- +3.4R on pure noise
           1.500     1.500   81     0.383  -0.038   -3.101
```

Three of twelve cells show positive returns on data with no edge in it. The
proposed plan — *"if win rate < 55% after 100 trades, adjust ONE parameter and
retest"* — would have found one of those cells and shipped it. `sensitivity()`
therefore reports the whole surface and flags when the sign flips across the
neighbourhood, rather than returning a winner.

### R, not win rate

With a stop at the opposite range edge and a 1.5R target, breakeven is a **40%**
win rate. 55% is +0.375R per trade; 64% is +0.600R. The directional structure is
genuinely favourable — that part of the plan is sound.

### Why an 89% or 83% win rate is not an edge

```
 1-wide sold for 0.15: breakeven win rate 85%  -> a quoted 83% is A LOSS
 1-wide sold for 0.20: breakeven win rate 80%  -> a quoted 83% is profitable
 1-wide sold for 0.25: breakeven win rate 75%  -> a quoted 83% is profitable
```

Credit spreads pay asymmetrically: high win rate, large loss when wrong. A win
rate quoted without the credit and the width **cannot be evaluated at all**. The
89%/83% ORB+0DTE figures came with neither.

### Data reality check

yfinance caps 15-minute history at roughly **60 days** and returns a short frame
rather than an error. The plan called for two years of 15m bars; you will not
get them there. Sixty days is ~12 tradeable weeks, which at 2-3 setups per week
is 25-35 trades, not the 100 the plan itself requires. Two years of intraday
bars needs IBKR, Polygon, Databento or similar.

## The win rate is a dial, not an achievement

`expectancy.py`. Read this before anything else in the repo.

On a driftless random walk, P(touch +R before -1R) is exactly **1/(1+R)**. So:

```
  target   free WR   breakeven   EV@70%WR   trades to prove 70%
    0.30     76.9%       76.9%     -0.090R                 never
    0.43     69.9%       69.9%     +0.001R             5,313,578
    0.60     62.5%       62.5%     +0.120R                   490
    0.75     57.1%       57.1%     +0.225R                   172
    1.00     50.0%       50.0%     +0.400R                    73
    1.50     40.0%       40.0%     +0.750R                    33
    3.00     25.0%       25.0%     +1.800R                    14
```

Set the target to 0.43R and you have a 70% win rate today, with zero skill and
zero expectancy. Simulation over barrier races reproduces the closed form. An
independent study entered ~900,000 zero-skill trades over twelve years of NQ
futures and built a **99% win rate that still lost money**, in five minutes.

**Free win rate and breakeven win rate are the same number.** That identity is
the whole argument: whatever your geometry hands you for free is exactly what
you need to break even. Everything above it is skill; nothing below it is.

### What a 70% target actually demands

| target | geometry gives | skill needed for 70% | EV at 70% | years to validate at 2/wk |
|---|---|---|---|---|
| 0.43R | 69.9% | **0.1pp** | +0.001R | 51,000 |
| 0.60R | 62.5% | 7.5pp | +0.120R | 4.7 |
| 0.75R | 57.1% | 12.9pp | +0.225R | 1.7 |
| 1.00R | 50.0% | **20.0pp** | +0.400R | 0.7 |

The counter-intuitive result matters most: **a wider target is cheaper to
validate**, because the skill gap it demands is larger and therefore easier to
detect. Two trades a week at a tight target is a design that cannot be
evaluated within a lifetime.

For calibration on what real systems run: trend-following CTAs operate at 35-48%
win rates with strong positive expectancy; market-makers at 70-85% on tiny
margins; option sellers at 80-90% with occasional catastrophic losses. None of
those numbers is comparable to another. Only expectancy is.

### Sizing

`size_position()` computes quarter-Kelly **on the Wilson lower bound**, not the
point estimate, and hard-caps at 2%. Kelly consumes your estimate of p, and at
n=100 with 70% observed the 90% interval runs ~62%-77% — which at a 0.75R target
is full-Kelly 11.3% versus 46.3%, a factor of four. Sizing on the point estimate
systematically overbets. It returns **zero** until the lower bound clears the
geometry.

## Your four requirements, and which one is actually the business

Your brief changed the problem: no buy/sell, no daily trades, 30 minutes of
latency is fine, "here is an opportunity, don't miss it". That removes the
speed competition entirely — and it makes three of your four items tractable
that were not before.

| # | What you asked for | Module | Verdict |
|---|---|---|---|
| 1 | Score news for whether it's a good investment | `news_model` + `patterns` | needs the 5 months. Real but slow. |
| 2 | How many times has X actually followed Y, and when is it due | `recurrence.py` | **works today** — it is counting, not forecasting |
| 3 | Which stocks are most news-reactive | `recurrence.py` | **works today** — measurement |
| 4 | Business opportunities, scored, plan if >80 | `venture.py` | **most likely to make you money** |

**Item 4 is the one to prioritise, and you called it "just one thing to add".**
Markets price securities — that is why items 1-3 keep returning "no edge".
Markets do **not** price business opportunities. Nobody has arbitraged away
"mid-size Delhi SaaS firms need SOC2 help and there are four local providers".
The inefficiency there is enormous and durable, because capturing it requires
doing work rather than placing an order.

## recurrence.py — counting beats forecasting

```
AVGO following a 2σ move in NVDA
  happened 113 times out of 137 shocks over 11.9 years
  rate 82%  (90% CI 77%–87%)   base rate 62%   lift +21%
  NVDA shocks 11.5x/year — next one due in ~22 trading days on average
  when it follows: median +1.64% (10–90% -0.66% to +4.30%)
  stability: first half 76% -> second half 88%
```

That is a **fact about the past** with an exact confidence interval. No
efficiency argument can make it wrong, which is why it needs no learning
period. What it cannot tell you is that the rate will hold — so every table
splits the rate across time halves and flags a pair as `decaying` when the
second half is materially worse. A falling rate means the pooled number
overstates what you would get now.

`recurrence_table()` ranks every pair by lift and marks `trustworthy` only when
there are 30+ shocks, the lower bound clears the base rate, and it is not
decaying. Scanning many pairs and reading the top one is still a selection —
the same bias measured elsewhere in this repo applies.

## investment.py — and the input I inverted

You described point 1 as: *a source says this is a good investment, here is the
return they say it can earn — rate it.* That description is also the shape of a
promotion. A system that ingests "sources say this can return 10x" and emits a
rating is a machine for laundering marketing into analysis.

**So a stated expected return is scored as a red flag, not as evidence.**
Audited prospectuses forecast risk; promotions forecast returns. The
`claimed_return` field exists only to record the claim and raise a flag — it can
never contribute positively.

A new listing has no price history, so there is nothing to backtest and no
honest probability of profit to compute. What *can* be assessed is the quality
of the evidence and the presence of structural hazards. The output is a
**diligence rating, not a return forecast**. A high score means "the disclosures
are real, the incentives are visible, the exit exists" — not "this will make
money". A low score means "you cannot evaluate this from what is available",
which is enough reason to pass.

Four flags are **fatal** and cap the rating at 15 regardless of everything else:
guaranteed return, anonymous principals, unregistered offering, returns funded
by new inflows. Polish is cheap, and those four are usually what the polish is
for. A perfect 100 on every diligence criterion still rates 15 with one of them
present.

```
Mainboard IPO, profitable manufacturer  [IPO]
  DILIGENCE RATING 76/100 — EVALUABLE — the evidence supports forming your own view
  red flags:
    [MODERATE] insiders hold a large share with a short or absent lock-up

[ 15] NEXUS token — exchange listing next week (TOKEN) · 5 flag(s) — DO NOT PROCEED
```

Per-class checklists cover IPO, token, fund, private, crypto and listed equity —
including token supply schedules and Indian VDA taxation.

## reference_class.py — "can it really do 8x?", answered from base rates

Flagging a claim is not evaluating it. This answers the claim the only way it
can be answered without a crystal ball: **how often have assets of that kind
actually delivered that multiple over that horizon.** The outside view. It needs
nothing about the specific asset, which is why it works on day one and cannot be
talked out of by a good story.

```
Claim: 8x over 1 year(s)
  reference class: NEW_TOKEN_1Y (CoinGecko, 20.2m tokens mid-2021 to end-2025)
  historically reached by ~1.2% of this class — roughly 82 to 1 against
  VERDICT: TAIL OUTCOME — possible, and unlikely enough to size accordingly
  base rate of near-total loss in this class: 53.2%
```

The reference data is sourced. **IPOs, 3 years out:** roughly two-thirds
underperform the market, 64% by more than 10%; outperformers are ~29% of the
total but the top decile averages over 300% market-adjusted. **New tokens:** of
~20.2m listed between mid-2021 and end-2025, 53.2% are no longer actively
traded — "dead" meaning near-zero volume, abandoned development and a 99%+
drawdown. The modal outcome for a new token is not a poor return, it is total
loss.

Shorter horizons scale the base rate down, because less time makes a large
multiple rarer, not commoner — a detail promotional material reliably inverts.

## reference_class.py — the carry test, for "buy it and store it"

Your copper example is a good thesis and usually a bad trade, for reasons
unrelated to whether the shortage is real:

```
Storage thesis: copper, 2 year(s)
  carry: storage 3.0% + insurance 0.5% + financing 8.0% = 11.5%/yr
  BREAKEVEN: price must reach 12,046.85 (+26.8%) just to lose nothing
  the futures curve already implies +7.4% over this horizon
  VERDICT: storage is UNECONOMIC. The forward price sits 19.4% below your
  breakeven. Being right about the shortage is not enough — the market must be
  wrong by more than your carry.
```

Two things kill it. **Carry:** warehousing, insurance and financed capital
compound daily, so the price must rise by more than the carry before you make
anything. **Crowding:** a shortage forecast everyone can read is already in the
spot price, so what you would be buying is the gap between the shortage and the
shortage already priced — much smaller than the shortage.

This is why a correct forecast can still lose money, and why commodity views are
usually expressed through futures or producer equities rather than warehouses.
`storage_thesis_questions()` lists what has to be answered first: forward curve
shape, who is selling to you at spot, flow deficit versus stock deficit,
substitution threshold, and the exit.

## venture_news.py — why a news scan cannot produce an 80

The scanner maps stories to gap types and scores what a headline can actually
evidence. It stops short of a plan, deliberately.

A first version of this scored the full rubric from headlines. Its arithmetic
ceiling across every gap type at maximum source strength was **66.1**, against a
plan threshold of 80 — the full-plan branch could never fire. Briefs forever,
silently.

That is not a calibration bug. It is the rubric telling the truth. The two
heaviest criteria are demand evidence (18) and distribution (18), and **a
headline cannot answer either**. No article tells you whether you can reach a
paying buyer in 60 days or whether you can do the work.

So the scan produces **candidates** carrying a current score, a `ceiling` (best
case if every unknown resolves well), and the list of what the news could not
answer:

```
[59 now, up to 83] Hospitals in eastern states report no distributor for devices
  gap type: distribution gap
  the news cannot answer these; you must:
    - distribution: Can you reach a paying customer in the first 60 days?
    - skill fit: Can you do the work, or learn it in under 3 months?
    - demand evidence: Is someone already paying for a worse version?
  CAN reach the 80 plan threshold even if every unknown resolves well

[45 now, up to 69] Palm Oil supply thesis
  commodity thesis — run the carry test before assuming storage is profitable
  CANNOT reach the 80 plan threshold even at best case
```

The ceiling is the useful number: a candidate at 59 that can reach 83 is worth
an evening; one at 45 that tops out at 69 is not. `enrich()` recomputes once you
answer, and refuses to let you overwrite what the news actually evidenced —
overriding that would discard the only part of the score not sourced from your
own optimism.

One candidate per story, and cluster quality is taken from the **best** outlet
rather than whichever published first: if a weak blog breaks a story and Reuters
confirms it, the evidence is Reuters-grade.

## venture.py — a rubric, and what it weights

Nine criteria, weights summing to 100. Note the two heaviest, at 18 points each:
**demand evidence** and **distribution** — whether someone already pays for a
worse version, and whether you can reach a buyer in 60 days without paid ads.
Then **time to first revenue** at 14. Market size is not scored at all, because
a large market has never been why a small business survived.

Above 80 produces a full plan built around what kills small ventures: first
three named buyers, unit economics with an explicit kill criterion, cash
conversion, skills gap, and the three weakest rubric items with a two-week test
for each. Below 80 gets one line naming its two biggest gaps and nothing more —
writing a full plan for a weak idea makes it look considered.

Every criterion must be scored or construction fails: a skipped criterion is a
silent 10, which is how weak ideas pass.

### Gap discovery

Scoring an idea someone hands you is the easy half. `GAP_TYPES` covers seven
mismatches worth hunting — unserved segment, supply chain shift, regulatory
trigger, capability gap, distribution gap, service around a product, price
umbrella — each with where the signal shows up **and what would confirm it is
real**. Almost every apparent gap is already served by someone you have not
found, too small to sustain anyone, or blocked for a reason invisible from
outside. The confirmation step separates those from a genuine opening.

On your examples: import arbitrage and dropshipping are real businesses that
produce income, but they score near zero on `durability` because the entry
barrier is "found a supplier". `durability_warning()` flags this explicitly —
**a job that pays, not an asset that compounds.** Fine if that is what you want,
but margins compress as others arrive, so plan the next one while this one works.

The score is a **structured judgment**, not an empirical probability — there is
no population of comparable ventures to calibrate against. Its value is
consistency: the same nine questions asked of every idea, so the exciting ones
don't get an easier ride.

## Gates

Every gate must pass or the answer is HOLD / no alert.

**Model B**

| Gate | Default |
|---|---|
| model out-of-fold Brier skill | > 0.002 |
| P(direction) **lower bound** | >= 0.60 |
| calibration-bin support | >= 40 |
| expected move vs costs | > 10bps equity, 35bps crypto |
| edge over base rate | >= 2pp |
| data freshness | <= 4 days |

**Model C**

| Gate | Default |
|---|---|
| lagged link survives FDR | q <= 0.10 |
| historical shocks observed | >= 40 |
| direction hit-rate lower bound | >= 0.58 |
| edge over unconditional base | >= 3pp |
| mean response vs costs | > 15bps |

---

## On the message format you asked for

You asked for messages like *"20% upside, buy, score 90%"* and *"10% affection,
confidence 90%"*.

The system will not print those, and the reason is arithmetic rather than
caution. A 20% one-day move in a mega-cap is roughly a 5-sigma event; 90%
confidence in one requires evidence that does not exist in daily data. Model C
reports a mean response *with* a 10–90% band precisely so you can see that a
"10% response" claim sits nowhere near the observed distribution. What you will
actually see is `+0.8%` with a band from `-1.2%` to `+2.9%`, and most days you
will see nothing at all.

If a build ever shows you "+20%, score 90%", that is the bug report.

---

## Known limitations

1. **Residual calibration optimism.** Isotonic is fit on out-of-fold predictions
   and evaluated on the same set. Standard practice, mildly optimistic. The null
   control bounds how much.
2. **`yfinance` adjusts prices retroactively** for splits and dividends. Old bars
   in a download today are not what you saw then.
3. **Survivorship bias.** The universe is today's largest names, selected by
   having gone up. Backtests over it are biased upward. Fixing it needs
   historical index constituent data.
4. **The contagion candidate list is hand-specified.** Every pair is tested and
   almost all rejected, so it is a hypothesis space rather than a set of beliefs
   — but a genuinely related asset absent from the list is invisible.
5. **No handling for delisted dependents.** Names that failed are missing from
   the screen entirely, which biases it.
6. **Network relationships decay.** The screen is rebuilt each run rather than
   cached; a stale network is worse than none because it looks authoritative.
7. **Lexicon classifier is weak.** Cannot read negation or whether a story was
   already priced in. Wire `LLMClassifier` to a real model.
8. **No position sizing or portfolio risk.** Model C alerts are especially
   correlated — one anchor shock can fire five dependents that are all the same
   trade.

---

## Layout

```
sigbot/
  types.py           dataclasses and provider protocols
  stats.py           Wilson, Brier, ECE, reliability — pure, no I/O
  features.py        point-in-time features; leakage-tested by truncation
  daily_model.py     Model B: OOF-calibrated logistic regression
  decide.py          the ONE place Model B's BUY/SELL/HOLD is decided
  backtest.py        walk-forward with costs and baselines
  contagion.py       Model C: HC1 regression, BH-FDR screen, event study
  news_model.py      Model A: entity match, dedupe, impact scoring
  opportunities.py   Model D: thesis cards, no scores
  shadow.py          SQLite forward ledger, append-only
  messenger.py       console / file / webhook sinks, formatting
  runner.py          daily | news | contagion | opportunities | resolve | report
  providers/         market data (real + synthetic panels) and news adapters
  tiers.py           evidence tiers and outcome classification
  patterns.py        pattern registry: prune, promote, confirm out-of-sample
  microstructure.py  signal specs with mechanism/detector attestation
  confluence.py      combination lift with measured, not assumed, independence
  orb.py             opening range breakout: rules, backtest, sensitivity
  expectancy.py      geometry vs skill, sample requirements, Kelly sizing
  skips.py           counts swallowed failures so a thin answer says it is thin
  doctor.py          fifteen health checks, each with the command that fixes it
  recurrence.py      how often has this happened, and when is it due again
  venture.py         business opportunity rubric, gap discovery, plan generator
  investment.py      diligence rating for IPOs, tokens, funds — flags, not forecasts
  reference_class.py base rates for claimed returns; carry test for storage theses
  venture_news.py    news -> business candidates, with an honest score ceiling
tests/               182 tests: leakage, calibration, gates, null AND power,
                     tiers, selection-bias correction, idempotency, attestation,
                     ORB, geometry-vs-skill, sizing, recurrence, venture rubric,
                     investment red flags, gap discovery, base rates, carry,
                     claim parsing, news-to-venture bridge
scripts/             backtest and contagion CLIs
```
