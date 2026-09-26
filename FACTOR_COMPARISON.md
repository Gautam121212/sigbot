# The 100-factor systematic comparison (Steps 1-3)

Step 1: 20 profitability factors per model (100 total), each a single variable.
Step 2: compare against what sigbot HAS and what WORKED in testing.
Step 3: the gaps — factors sigbot is missing that are worth testing.

Legend for each factor: **[HAS]** sigbot uses it · **[TESTED-worked]** ·
**[TESTED-failed]** · **[GAP]** not in sigbot, worth testing · **[—]** needs
data sigbot can't reach.

---

## STOCKS (20 factors)

1. Momentum (12-1 month relative strength) — **[GAP]** the #1 institutional
   factor; sigbot has momentum-breakout but not cross-sectional 12-1 momentum.
2. Value (P/E, P/B, EV/EBITDA cheapness) — **[—]** needs fundamentals (has some).
3. Quality: gross profitability — **[GAP]** strong factor, not used.
4. Quality: low accruals (earnings quality) — **[GAP]** Sloan's anomaly, not used.
5. Quality: high ROE — **[—]** fundamentals.
6. Quality: low leverage — **[—]** fundamentals.
7. Low-volatility anomaly (low-beta stocks outperform) — **[GAP]** not used.
8. Size (small-cap premium) — **[GAP]** sigbot has no size tilt.
9. Capitulation / deep oversold — **[HAS, TESTED-worked]** panic-capitulation.
10. Hammer + oversold candle — **[HAS, TESTED-worked]**.
11. Volume-price divergence (accumulation) — **[HAS, TESTED-partial]**.
12. Big-winner precursor (high-vol + rising + volume) — **[HAS, TESTED-worked]**.
13. Post-earnings drift — **[TESTED-failed]** priced same-day now.
14. Mean-reversion after 3 down days — **[GAP]** Connors, backtested since 1990s.
15. RSI(2) < 10 with 200MA filter — **[GAP]** the QuantifiedStrategies staple.
16. 52-week high proximity (breakout) — **[TESTED-failed]** near-52w failed.
17. Sector relative strength — **[HAS]** sector mean-reversion (opportunities).
18. Analyst revision momentum — **[—]** needs estimate data.
19. Seasonality (turn-of-month, sell-in-May) — **[GAP]** not used.
20. Idiosyncratic volatility — **[GAP]** low-idio-vol is a quality proxy.

STOCK GAPS worth testing: **momentum 12-1, gross profitability, low accruals,
low-vol anomaly, size, 3-down-days, RSI(2), seasonality, idio-vol** (9 gaps).

---

## CRYPTO (20 factors)

1. Funding rate (crowded longs) — **[TESTED-failed]** flips out of sample.
2. Open interest build — **[—]** needs derivatives feed (proxy only).
3. MVRV ratio — **[—]** on-chain.
4. SOPR — **[—]** on-chain.
5. NUPL — **[—]** on-chain.
6. Exchange netflow — **[—]** on-chain.
7. Whale accumulation — **[—]** on-chain.
8. Realized price distance — **[—]** on-chain.
9. Halving-cycle timing (18mo post-halving) — **[GAP]** datable, testable!
10. Low-volume-drop rebound — **[HAS, TESTED-worked]**.
11. Below-7d-MA dip — **[HAS, TESTED-worked]**.
12. Crowding avoid (vol rising, price flat) — **[HAS, TESTED-worked]**.
13. Bitcoin dominance / alt rotation — **[TESTED-failed]** cascade flips.
14. Relative strength vs BTC — **[TESTED-failed]** flips.
15. RSI(2) extreme — **[TESTED-failed]**.
16. Weekend effect — **[TESTED-failed]**.
17. Volatility squeeze — **[TESTED-failed]**.
18. Magnitude (move-size) — **[HAS, TESTED-worked]** regime-independent.
19. Stablecoin supply ratio — **[—]** on-chain.
20. New-30d-high momentum — **[TESTED-failed]** flips.

CRYPTO GAPS worth testing: **halving-cycle timing** (the one datable gap). The
rest need on-chain/derivatives data. Crypto direction is structurally hard;
this is honest, not a search failure.

---

## NEWS (20 factors)

1. Earnings surprise (SUE) — **[HAS, TESTED-worked]** confirmed-surprise.
2. Pre-earnings drift — **[HAS, TESTED-worked]** the new leading signal.
3. Surprise magnitude → move size — **[HAS, TESTED-worked]**.
4. Analyst revision momentum — **[GAP]** needs estimate data.
5. Guidance change — **[—]** needs guidance data.
6. Post-earnings drift — **[TESTED-failed]**.
7. Beat-while-oversold context — **[TESTED-marginal]**.
8. Sequential beats (2 in a row) — **[TESTED-failed]**.
9. Turnaround beat (beat after miss) — **[TESTED-failed]**.
10. News volume spike / attention — **[GAP]** the attention signal (partly built).
11. Sentiment-price divergence — **[GAP]** GDELT tone, not fully tested.
12. Earnings-call language (peaks next day) — **[GAP]** needs transcripts.
13. Headline-vs-body sentiment gap — **[GAP]** GDELT, testable.
14. Sector news contagion — **[GAP]** overlaps follow-on (dead).
15. Macro-news regime filter (VIX) — **[GAP]** could gate news signals.
16. Insider buying + news — **[—]** needs insider data.
17. Options flow around news — **[—]** needs options.
18. Estimize crowd estimates — **[—]** needs crowd data.
19. 13F institutional flow — **[—]** needs filings.
20. Per-firm surprise memory — **[GAP]** each firm's own reaction history.

NEWS GAPS worth testing: **analyst revisions, attention-volume, sentiment
divergence, headline-body gap, macro regime filter, per-firm memory** (6 gaps).

---

## VENTURES (20 factors)

1. Power-law portfolio (20+ bets) — **[HAS]** power_law.py.
2. Follow-on reserve (40%, double winners) — **[HAS]** in the model.
3. Optimize outlier exposure not hit rate — **[HAS]** the core principle.
4. Series-A signal (institutional validation) — **[GAP]** needs deal data.
5. Underwriter/backer quality — **[—]** needs deal data.
6. Team/repeat-founder track record — **[—]** needs data.
7. TAM growth — **[—]** needs data.
8. Revenue-growth durability — **[—]** needs data.
9. Gross-margin trend — **[—]** needs data.
10. Cash runway — **[—]** needs data.
11. Unit-economics inflection — **[—]** needs data.
12. Geographic/information asymmetry — **[GAP]** emerging-market edge concept.
13. Barbell (capped downside, large upside) — **[HAS]** ventures.py.
14. Positive expected value gate — **[HAS]** venture_risky_bet.
15. Sector-timing (washed-out sectors) — **[HAS, TESTED-worked]** mean-reversion.
16. Macro adjustment (World Bank) — **[HAS]**.
17. Lock-up expiry (IPO) — **[GAP]** datable calendar edge, not built.
18. Insider selling at IPO — **[—]** needs IPO data.
19. Oversubscription inversion — **[—]** needs IPO data.
20. First-day-pop → long-run underperformance — **[—]** needs IPO data.

VENTURE GAPS worth testing: **lock-up expiry** (datable). Most need a deal feed.

---

## IDEAS (20 factors — opportunity/thesis detection)

1. IPO pattern detection — **[HAS]** IPO_PATTERNS.
2. Macro-shock detection — **[HAS]** MACRO_PATTERNS.
3. Opportunity pattern (new markets, incentives) — **[HAS]** just added.
4. Thesis-strength (checks passed) — **[HAS]** idea_risky_bet.
5. Source quality weighting — **[HAS]** venture news scanner.
6. Novelty (not already priced) — **[GAP]** freshness check, partial.
7. Regulatory-door detection — **[HAS]** in opportunity patterns.
8. Funding-round detection — **[HAS]** in opportunity patterns.
9. Sector-boom detection — **[HAS]** in opportunity patterns.
10. Attention-surge (GDELT volume) — **[GAP]** attention signal, partial.
11. Cross-source confirmation — **[GAP]** multiple sources agreeing.
12. Time-decay (idea expiry) — **[HAS]** idea state/eta.
13. Geographic-asymmetry (emerging markets) — **[GAP]** the info-edge concept.
14. Catalyst-date proximity — **[GAP]** how close is the trigger.
15. Contrarian-sentiment (fear = opportunity) — **[GAP]** GDELT tone inversion.
16. Insider-language (executive confidence) — **[—]** needs transcripts.
17. Supply-chain ripple — **[—]** needs linkage graph.
18. Policy-cycle survival — **[HAS]** in opportunity checks.
19. Competitive-density (how many others moving) — **[HAS]** in checks.
20. Access-feasibility (can a person actually act) — **[HAS]** in checks.

IDEA GAPS worth testing: **novelty, attention-surge, cross-source confirmation,
geographic asymmetry, catalyst proximity, contrarian sentiment** (6 gaps).

---

## STEP 3: THE FULL GAP LIST — new things to test (the answer)

Comparing all three (the 100 factors × what sigbot has × what worked), the
gaps that are REACHABLE with sigbot's data and worth testing:

**Stocks (testable now, high priority):**
1. Momentum 12-1 (cross-sectional) — the #1 institutional factor, sigbot lacks it
2. Gross profitability (quality) — if fundamentals reachable
3. Low accruals (earnings quality / Sloan)
4. Low-volatility anomaly (low-beta outperforms)
5. Size premium (small-cap tilt)
6. 3-down-days mean-reversion (Connors)
7. RSI(2) < 10 + 200MA filter (Connors)
8. Seasonality (turn-of-month)
9. Idiosyncratic volatility

**Crypto:**
10. Halving-cycle timing (18-month post-halving)

**News:**
11. Attention-volume spike (partly built)
12. Sentiment-price divergence (GDELT)
13. Headline-body sentiment gap
14. Macro regime filter on news
15. Per-firm surprise memory

**Ideas:**
16. Novelty / not-yet-priced
17. Cross-source confirmation
18. Contrarian sentiment (fear = opportunity)

That's **18 testable gaps** — the "at least 10-20 new things" you predicted.
The highest-value cluster is the STOCK FACTORS (momentum 12-1, quality,
low-vol, size, Connors), because they are the institutional core sigbot never
had — it built candle/oversold signals but skipped the proven academic factors.

NEXT: test these gaps one cluster at a time, adopt only what survives
out-of-sample, and update the indicators with what works.

---

## THE THIRD COMPARISON — done from the DATA (was missing before)

The gap the user caught: I listed factors and checked what sigbot has, but
never went into the historical data to find what ACTUALLY gave big moves, per
model. Done now:

### CRYPTO (reverse-engineered from actual 30%+ movers)
Big crypto winners before a 30%+ move vs normal days: nearly IDENTICAL on RSI,
volume, volatility. Only difference: winners had positive 30d momentum (+3.8%
vs -6.3%). But tested out-of-sample, "already recovering" FLIPS (-14.7/-2.7/
+7.2%) — it just tracks the bull/bear regime. CONFIRMED: crypto liquid majors
have no stable direction edge, even reverse-engineered from the winners. The
magnitude signal remains its only real edge.

### NEWS (reverse-engineered from actual 10%+ post-earnings movers)
FOUND: surprise SIZE predicts the CHANCE of a big move, cleanly and monotonic:
  small surprise (<5%):   5.2% produce a 10%+ move
  medium (5-25%):         7.7%
  huge (25%+):           16.8%  (3.2x the small rate)
This is the news BLOWUP FLAG — a huge surprise triples the odds of an explosive
move. sigbot uses surprise size for SIZING but not as a big-move/blowup flag.
GAP -> build the news big-mover signal.

---

## PROFESSIONAL RETURN BENCHMARKS — the yardstick (was missing entirely)

The gap: sigbot had no reference for what returns pros consider good/exceptional,
so "+5%/yr" was un-judgeable. From hedge-fund/quant/crypto-fund/VC data:

CORE (systematic equity, market-neutral):
  hedge funds ~10.7%/yr long-run · quant funds 10-17% · sweet spot 15-25% at
  Sharpe 1.5-2 · Sharpe 1.0 beats 95% of funds, 1.5+ is elite (Renaissance).
  Thresholds: <8% worthless, 8-15% decent, 15-25% good, 25%+ exceptional.

RISKY (aggressive systematic, crypto quant):
  30-50%/yr achievable but with 30%+ volatility · crypto quant Sharpe ~1.5.
  Thresholds: <15% worthless (must beat core to justify risk), 30% good, 50%+ exceptional.

VERY-RISKY (venture/blowup):
  VC top-quartile 15-27% net IRR at FUND level · 1-3 of 20-30 bets drive 50-80%
  of returns · blowup range -40% to +1,111%, judged on the TAIL not the average.
  Thresholds: 8% decent, 15% good, 27%+ exceptional.

MODEL GRADES (sigbot vs these benchmarks, on $100k):
  STOCKS panic-capitulation: +32%/yr -> EXCEPTIONAL (but optimistic backtest)
  VENTURES power-law:        +20% IRR -> GOOD (competitive with VC)
  BLOWUP big-winner tail:    +15%    -> GOOD (for the tier)
  NEWS confirmed-surprise:   +2.3%   -> WORTHLESS (below the 8% floor)
  CRYPTO magnitude only:     ~0%     -> WORTHLESS (no direction edge)

ACTION: news and crypto are below the professional floor -> need real edges or
retirement; stocks/ventures/blowup are competitive. `runner grades` shows this.
