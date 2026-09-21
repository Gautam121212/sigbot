# COMPARISON — sigbot measured against the trader playbook

**Companion to PLAYBOOK.md.** The playbook describes how professional
traders work; this file holds sigbot's side — what it actually does,
measured against that guide, and where the two differ.

Every claim carries an evidence tag, because this project has learned the
hard way that sound-sounding professional rules can invert on a particular
setup:

| Tag | Meaning |
|---|---|
| **TESTED** | Measured on historical data here; the number is quoted |
| **SOURCED** | Documented practitioner behaviour, not yet tested on this data |
| **UNTESTABLE HERE** | No historical data reachable to test it (stated why) |
| **REJECTED** | A real professional rule that inverted when tested on this setup |

---

## The trader's day, in one paragraph

Before the open they check what changed overnight and what the risk budget
is: how much is already at risk, whether they are on a losing streak, how far
below the high-water mark they are. During the session they spend attention
in order of how fast opportunities decay — breaking news first, then setups,
then slow themes. They size every position from where they will be proved
wrong, never from how confident they feel. They cut losers at the stop without
debate and let winners run. After the close they record every trade, win or
lose, and review what the record says rather than what they remember.

---

## Principles that apply to every model

| Behaviour | Professional | Sigbot | Evidence |
|---|---|---|---|
| Judge by money, not accuracy | Expectancy in R | `expectancy.py`; edge quoted as +0.042 R | **TESTED** — the setup that passed every accuracy test lost to holding |
| Risk per trade | 1% of capital, sized from the stop | `risk.py`, 1% | **TESTED** — conviction sizing put most money where swings were widest |
| Exits | Stop scaled to volatility; winners run | `exits.py`, 3×ATR, no target | **TESTED** — +0.759% → +1.424% a trade |
| Stop enforced when scored | Always | Stocks: yes (B84) | **TESTED** end to end |
| Losing streak | Stand aside after several in a row | Pause after 4 | **TESTED** — −0.559 R after 4 losses vs +0.241 R otherwise |
| Daily loss limit | Stop for the day | 3% | **SOURCED** |
| Drawdown | Cut size, never add | Halve past 10%, quarter past 20% | **SOURCED** |
| Correlated positions | Treat as one bet | ≤2 per sector, ≤6 open | **TESTED** — 67% of a day's signals came from one sector |
| Capital vs risk | Separate limits | ≤75% deployed | **TESTED** in dry run |
| Liquidity | Avoid thin names | ≥500k shares/day | **TESTED** — +1.514% vs +1.136% |
| Attention | Fastest-decaying first | `priority.py` by half-life | **SOURCED**; queue tested |
| Record everything | Journal wins and losses | Every signal recorded, taken or not | **TESTED** — B36/B52/B68 |

---

## 1 · News scanner

**How the trader sees it.** A headline is worth something for hours, often
minutes. The question is never "is this news good?" — it is "is this already
in the price?" By the time a story is widely reported, most of the move has
often happened. They care about *surprise relative to expectation*, not about
the headline's tone.

**What they act on.** Material, unexpected news about a specific liquid name:
guidance changes, regulatory decisions, deal announcements. They ignore
opinion pieces, recaps of moves that already happened, and anything vague.

**Speed.** Fastest of any model. If they cannot act within the first hours,
they usually do not act at all.

**How they protect themselves.** Small size — news trades gap and reverse.
They know that a strongly positive story on a stock already up sharply is as
likely to be sold as bought.

| | Sigbot today | Gap |
|---|---|---|
| Speed | Runs every 3h; first in the priority queue | Adequate for a 24h window, too slow for intraday reactions |
| Priced-in check | None — scores the story, not the surprise | **Main gap.** Needs the price move *before* the story as a filter |
| Record | 80 clean checks, 57.5% vs 46.9% chance | Too early to judge; target 300 |

**Evidence:** UNTESTABLE HERE for backtesting — no historical headline archive
is reachable, so the news model can only be measured forward. The event-study
file (`events.py`) is the substitute: it records what actually happened after
past events of each kind.

---

## 2 · Daily outlook

**How the trader sees it.** A professional does not forecast every stock
every day. That is a machine's habit. Most sessions contain nothing worth
acting on, and forcing an opinion onto them pays costs to find noise.

**What they act on.** Almost nothing, on most days. That is the point.

| | Sigbot today | Gap |
|---|---|---|
| Behaviour | Forecast every name every session | **Structural** — fires ~100% of what it looks at (B69) |
| Record | 45.8% vs 45.0% chance on 1,409 clean checks | No edge |
| Replacement | `stocks` scan: wide look, narrow record | Already built; daily now serves as the baseline |

**Evidence:** TESTED — 141,123 replayed decisions at 51.4% vs a 52.2% base
rate. Kept only as the benchmark the selective models are measured against.

---

## 3 · Follow-on moves (contagion)

**How the trader sees it.** When a large company moves hard, its suppliers,
competitors and customers often follow — sometimes the same day, sometimes
over weeks. A professional knows the specific relationships (who supplies
whom) rather than relying on price correlation alone.

**What they act on.** A large, news-driven move in a leader, followed by the
lagging names that have not yet reacted, where the business link is real.

**Speed.** Same session to a few days.

| | Sigbot today | Gap |
|---|---|---|
| Link discovery | Statistical lead-lag between prices | Misses business relationships; finds spurious ones |
| Recording | Every triggered link recorded (fixed, B52) | — |
| Record | Links scored 37–39% against a ~51% base | **Worse than chance** on this universe |

**Evidence:** TESTED — measured worse than chance. Runs at reduced priority
because of it. A business-relationship map would be the fix; none is
reachable here.

---

## 4 · Crypto

**How the trader sees it.** Crypto is a momentum market, not a
mean-reversion one. It trades 24 hours, moves in regimes, and punishes
bottom-fishing. Professionals follow the trend and size down because the
swings are several times those of equities.

**What they act on.** Strength above the medium-term trend. They avoid
catching falling coins.

| | Sigbot today | Gap |
|---|---|---|
| Behaviour | 3-hour direction forecasts on many pairs | No edge on 5,135 checks |
| Setup direction | — | The stocks washout setup must **never** be applied here |

**Evidence:** TESTED this session on five major coins over the past year:

| Condition | 5-day return | Won |
|---|---|---|
| Any day | −0.389% | 42.9% |
| After a 15%+ weekly drop | **−3.636%** | 34.0% |
| Above 50-day average | −0.101% | 41.5% |
| Below 50-day average | −0.551% | 43.7% |

Buying crypto washouts lost ten times the baseline. Caveats: one year only
(the free data tier), five coins, a falling year, 50 washout cases. The
direction is the finding; the magnitude is not reliable.

---

## 5 · Opportunities

**How the trader sees it.** Opportunities are events with windows — listings,
restructurings, sector dislocations. The trader researches the specific case,
works out what could go wrong, and caps the downside before thinking about
the upside. They are sceptical of stories that are too neat.

**IPOs specifically:** the first-day gain goes largely to allocated
institutions, not to buyers on the open. A professional usually waits for the
first earnings report or for the post-listing lock-up to expire.

| | Sigbot today | Gap |
|---|---|---|
| Output | Cards scored on how much of the question set is answered | Measures completeness, not attractiveness |
| Dead windows | Removed when expired or unanswerable in time | Adequate |
| Record | 0 scored checks | Cannot be judged: each opportunity is a one-off |

**Evidence:** UNTESTABLE HERE — single events cannot be backtested as a
series. Judged on process, not on a hit rate.

---

## 6 · Ideas

**How the trader sees it.** An idea is a thesis, not a trade. It becomes a
trade only when there is an entry, a stop and a reason it is worth acting on
*now*. Most ideas are kept on a watchlist and never traded.

| | Sigbot today | Gap |
|---|---|---|
| Colour | Green when a majority of the case is answered | Completeness, not timing |
| Expiry | Dropped when the window shuts or cannot finish | Adequate |

**Evidence:** UNTESTABLE HERE, for the same reason as opportunities.

---

## 7 · Paper trading

**How the trader sees it.** The paper book is the rehearsal, and it must be
honest: real costs, real stops, real sizing, losses recorded as fully as
wins. Its only job is to show whether the process makes money before money is
at risk.

| | Sigbot today | Gap |
|---|---|---|
| Sizing | Risk-based for stop-carrying models, flat otherwise | Fixed (B80) |
| Stops | Honoured via resolution | Verified end to end this session |
| Costs | Flat 0.15% a side | Real cost rises with size and spread — overstates results |

**Evidence:** TESTED — a stopped trade replays at its stop for −1.03 R.

---

## 8 · Stocks (after paper trading)

**How the trader sees it.** Stocks that have been paper-traded with a
positive record earn a place on the watchlist. The trader still sizes each
one from its own stop, still respects the sector cap, and still stands aside
after a losing streak — a good record on one name is not a reason to break
the rules on the next trade.

| | Sigbot today | Gap |
|---|---|---|
| Selection | Wide scan, two tiers (proven / risky) | Nothing currently proven |
| Proven bar | Three positive eras AND beats holding | Correctly strict |
| Risk | All breakers live and seeded from real results (B83) | — |

**Evidence:** TESTED throughout. What reaches the account: +0.042 R a trade,
+0.241 R outside losing clusters.

---

## Professional rules that were tested and REJECTED on this setup

These are sound rules for trend-following. The stocks setup buys washouts,
the opposite mechanism, and each inverted:

| Rule | Result |
|---|---|
| Only go long above the index's 200-day average | Below: +1.575%, above: +1.280% |
| Don't hold through earnings | Through them: +2.265%, clear: +1.431% |
| Step aside when volatility explodes | Cut returns; made 2020 worse |

**Note the symmetry:** crypto is a momentum market, so for crypto the
trend-following rules are the *right* ones. The lesson is not "ignore
professional rules" — it is "know which kind of market a rule was written
for".

---

## Measured this round — the playbook against sigbot on history

All figures on liquid US large caps (Shibui), 2016 to present, in units of
risk with a volatility-scaled stop and a ten-day window.

### Stocks: the two schools, overall and under pressure

| | Overall | 2020 crash | 2022 bear | Trades |
|---|---|---|---|---|
| Playbook momentum (buy breakouts to new highs) | **+0.098 R** | **+0.133 R** | −0.069 R | 15,175 |
| Sigbot washout (buy extreme selling) | +0.043 R | −0.258 R | **+0.163 R** | 6,807 |

Momentum earned more than twice the edge on more than twice the trades — and
the two **failed in opposite years**. Sigbot now runs both. Momentum is
positive in all three eras (+0.074 / +0.064 / +0.137 R) but trailed simply
holding in 2016-19, so it sits in the RISKY tier under the same bar that
demoted the washout setup. **Evidence: TESTED.**

### Follow-on moves: does the sector follow a leader?

| Regime | Cases | Next day, in the leader's direction | Followed |
|---|---|---|---|
| All | 745,570 | −0.214% | 48.1% |
| Normal | 494,153 | −0.050% | 48.8% |
| 2020 crash | 131,196 | −1.109% | 41.3% |
| 2022 bear | 120,221 | +0.089% | 52.5% |

After a leader moves 4%+ the sector slightly **reverses** the next day, and
reversed hard in the 2020 crash. The playbook's "leaders drag their groups" is
a weeks-to-months observation; as a next-day rule it does not hold here, which
agrees with the model's worse-than-chance record. Sigbot now uses the
professional structure — 24 large-cap leaders as anchors, the whole universe
as followers — but that structure alone does not create next-day edge.
**Evidence: TESTED.**

### Crypto: momentum yes, dip-buying no

Dip-buying stays blocked on crypto (−3.64% over five days after a 15% weekly
drop). The first guard blocked crypto entirely, which also blocked momentum —
the style the playbook says suits it. It now blocks only dip-buying.

### Promotion ladder — where sigbot stands

`runner promotion` evaluates the ladder from the real records. Today: **PAPER,
2 of 7 criteria met.** Blocking: fair history trails the index (+0.54% vs
+1.00% a month net), the unseen years earned nothing after costs, and there
are no closed paper trades yet.

**The arithmetic that matters most:** at the historical edge of about +0.04 R
a trade, reaching the evidence bar (t ≥ 2) needs roughly 2,500 trades — about
17 years at twelve a month. Waiting will not promote this edge. Only a larger
one can clear the bar in reasonable time.

Live execution is a constant set to off, and no broker code exists. The
ladder reports eligibility; it cannot place an order.

### Intake gate and new sources

Every news item and opportunity is judged ACT, LEARN or DROP before entering
the loop. Tested on real items: 4 act, 18 learn, 10 dropped of 32. Sources:
the RSS feeds plus **GDELT** (the keyless global news source OSIRIS draws on,
with a searchable three-month window) and the **USGS** significant-earthquake
and **GDACS** disaster feeds. News forecasts now record their source, so each
source builds the record the gate judges it by.

Found while building it: universe names were legal names ("Apple Inc. Common
Stock") that no headline contains, and they had replaced the curated names
with aliases — so the news scanner could not recognise the widened names by
name. And "45 km SW of Tokyo" matched the ticker SW. Both fixed.

### Monthly growth benchmark — corrected

**The first benchmark was wrong.** It chose stocks by their size today, which
used information nobody had at the time of each trade and kept the companies
that did well. Measured fairly — liquid **at the time**, over $20M traded a
day — and after costs:

| | 2016 to now | 2009–15 (never seen) |
|---|---|---|
| Sigbot: both schools | **+0.54%** a month | **≈ 0.00%** |
| Buy and hold the index | +1.00% | ≈ +1.1% |

Sigbot trailed the index in both periods. The washout school suffered most
from the old filter (+0.63% became +0.11% gross) — as predicted, because a
crashed stock that stayed down is exactly what that filter dropped.

**A limit no query can fix:** Shibui removes companies that later went bust
(SVB, Bed Bath & Beyond, First Republic, WeWork are absent), so even the fair
figures are upper bounds, and dip-buying is the most flattered.

**Change made:** live trading now requires $20M a day traded, so it trades
only the kind of stock that was measured. **Evidence: TESTED**, in-sample and
out-of-sample.

### The site: five models

Daily outlook was folded into **Stocks & funds**, and Tested setups into the
same scan. The site now shows the five models the playbook is organised by:
News scanner, Stocks & funds, Crypto, Follow-on moves, Opportunities. The
retired models' records stay in the ledger.

### Costs: estimated as desks estimate them

A flat 0.075% a side is replaced by spread plus square-root market impact,
using each name's daily traded value and volatility recorded at entry. On a
20,000 order: a mega cap 0.052% a side (cheaper than before), a mid cap
0.100%, a thin volatile name 0.377% (five times the old rate). Trades without
liquidity data keep the old rate. **Evidence: TESTED** end to end.

### Coverage: the 100-name board is gone

Every model drew from the 100-row watchlist. They now draw from the whole
tradable pool — **675 assets** (594 equities, 69 crypto, 12 funds). The
watchlist only decides what the site highlights.

---

## What is still genuinely missing

1. **A priced-in filter for news** — the move before the story.
2. **A business-relationship map for follow-on moves**, instead of price
   correlation alone.
3. **Realistic costs** that rise with size and spread.
4. **A live record.** Everything above that says TESTED was tested on
   history. The first months of live results are the only thing that can
   confirm it.
