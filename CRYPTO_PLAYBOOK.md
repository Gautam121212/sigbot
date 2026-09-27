# The crypto playbook — what forward-testing actually revealed

The user's push: understand how the market BEHAVES, don't just fit indicators.
This session forward-tested the crypto edges properly (turnover at time T ->
return AFTER T, avoiding reverse-causation) and studied the lifecycle of the
biggest actual runs. The truth is humbling and important.

## FORWARD TESTS killed two edges I would have shipped

1. TURNOVER edge — FAILED forward.
   Snapshot said high-turnover small caps = +26% (looked amazing).
   Forward test: high turnover at time T -> -3.8% over the next 14 days
   (WORSE than low turnover at -1.9%). The +26% was pure reverse-causation:
   coins that ALREADY pumped had high volume. Tested honestly, it inverts.

2. DEEP-DRAWDOWN edge — FAILED forward.
   Studying the biggest runs (Fantom +1152%, Sei +76%), they all started
   from coins down 40-90% — "beaten down survivors explode." But forward-
   tested across ALL coins and moments: deep drawdown (down 60%+) -> -4.0%
   over the next 30d. Coins NEAR their highs did better (+2.2%). The pattern
   was survivorship bias — I only saw the beaten-down coins that RECOVERED.

## WHAT THE PLAYBOOK ACTUALLY IS (the honest mechanics)

- Crypto is DOMINATED by one factor: the overall market regime (risk-on/off).
  In a bull phase almost everything rises; in a bear phase almost everything
  falls. Individual-coin signals are noise on top of this.
- Momentum (near highs) slightly beats mean-reversion (deep drawdown) forward,
  but weakly (+2.2% vs -4.0%) and both are regime-swamped.
- The BIGGEST winners (10x+) are unpredictable EX-ANTE from price/volume: which
  beaten-down coin explodes depends on narrative, listings, dev activity, and
  capital rotation that price data does not contain.

## THE REAL LESSON

Reverse-engineering finds patterns in the WINNERS (survivorship). Forward-
testing on ALL coins/moments is the only honest test, and it kills most of
them. What survives forward in crypto with free price data is: almost nothing
directional. The edge that WOULD work needs data the price series lacks —
on-chain flows, dev activity, social/narrative momentum, exchange listings —
the actual drivers of which coin the capital rotates into next.

This is the same conclusion as stocks (DEEP_RESEARCH_EXCEPTIONAL.md): free
price/fundamental data is efficient enough that ~market-regime returns are the
ceiling. The exceptional edge is a DATA edge (alt-data / on-chain), not a
signal-engineering edge. Every forward test this session confirms it.
