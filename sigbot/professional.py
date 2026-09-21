"""How an experienced trader responds, how sigbot responds, and what the data says.

WHY THIS FILE EXISTS
--------------------
The obvious way to make a system trade like a professional is to copy the
professional rulebook. This file records what happened when that was done
carefully: each rule was taken from practitioner sources and then TESTED on
the same historical entries before being adopted.

The headline result is uncomfortable and important. Of the widely repeated
professional rules tested here, half INVERTED on this system's setup. They are
sound rules — for the strategies they were written for. Most professional
advice is written for trend-following, and this setup buys washouts, which is
the opposite mechanism. A rule borrowed from one kind of strategy has to be
tested against the mechanism of the other before it can be trusted.

The rules that held are the ones about RISK rather than about ENTRY: size from
the stop, cut losers, let winners run, avoid illiquid names. Those survive a
change of strategy because they are about the arithmetic of losing, not about
predicting the market.

THE METRIC THAT MATTERS
-----------------------
Expectancy per trade in PERCENT flatters a risk-sized system. What reaches the
account is expectancy in R — return divided by the distance to the stop —
because position size is set so that one stop-out costs exactly one R.

    per trade, in percent      +1.247%
    per trade, in R            +0.042 R

At 1% risk per trade, +0.042 R is about +0.04% of the account per trade. That
is the honest size of the edge, and it is far smaller than the percentage
suggests. Every future claim of improvement should be quoted in R.
"""
from __future__ import annotations

from dataclasses import dataclass

ADOPTED = "ADOPTED"
REJECTED = "REJECTED"
UNTESTED = "UNTESTED"


@dataclass(frozen=True)
class Behaviour:
    """One situation, the professional response, and whether it held."""

    situation: str
    professional: str
    sigbot_before: str
    verdict: str            # ADOPTED / REJECTED / UNTESTED
    evidence: str           # the measurement that decided it


BEHAVIOURS: tuple[Behaviour, ...] = (
    Behaviour(
        situation="Deciding what to measure",
        professional="Judges a strategy by what it earns (expectancy), not "
                     "by how often it is right.",
        sigbot_before="Every gate, tier and colour rested on hit rate.",
        verdict=ADOPTED,
        evidence="The only setup that passed every accuracy test won 54.3% "
                 "vs 51.1% and still earned less than holding (+0.599% vs "
                 "+0.659% a trade), because its losses were nearly as large "
                 "as its wins."),
    Behaviour(
        situation="Deciding how much to buy",
        professional="Risks 1-2% of capital per trade and sizes the position "
                     "from the distance to the stop.",
        sigbot_before="Flat size, then conviction-weighted size.",
        verdict=ADOPTED,
        evidence="Conviction and volatility are correlated, so conviction "
                 "sizing put the most money where the swings were widest. "
                 "Risk sizing turns a 63%-wide stop into a 1.6% position."),
    Behaviour(
        situation="Deciding when to get out",
        professional="Cuts losers at a predefined stop, lets winners run.",
        sigbot_before="Exited on a fixed clock, whatever happened.",
        verdict=ADOPTED,
        evidence="Same 9,246 entries: fixed 10-day clock +0.759%, 3xATR stop "
                 "with winners left to run +1.424%. Nearly double, with a "
                 "LOWER win rate."),
    Behaviour(
        situation="Setting the stop distance",
        professional="Scales the stop to the instrument's normal movement.",
        sigbot_before="(first attempt) a fixed 5% stop.",
        verdict=ADOPTED,
        evidence="A fixed 5% stop returned -0.065% — it sat inside the noise "
                 "of names that move 4% a day. The ATR-scaled stop returned "
                 "+1.424%."),
    Behaviour(
        situation="Choosing which names to trade",
        professional="Avoids thinly traded names (commonly under 500k "
                     "shares a day).",
        sigbot_before="No liquidity check.",
        verdict=ADOPTED,
        evidence="Liquid names +1.514% vs thin names +1.136% on the same "
                 "entries."),
    Behaviour(
        situation="Many signals firing on the same day",
        professional="Caps exposure per sector; treats correlated positions "
                     "as one bet.",
        sigbot_before="Counted positions, not correlated risk.",
        verdict=ADOPTED,
        evidence="67% of an average day's signals came from one sector; the "
                 "worst day fired 263 at once."),
    Behaviour(
        situation="The broad market is falling",
        professional="Only goes long when the index is above its 200-day "
                     "average — do not fight the tape.",
        sigbot_before="No regime filter.",
        verdict=REJECTED,
        evidence="Inverted on this setup: index below its 200-day +1.575% "
                 "vs above +1.280%, consistent at 180/200/220 days. Washouts "
                 "pay best when fear is widest."),
    Behaviour(
        situation="An earnings report is due during the hold",
        professional="Avoids holding through earnings — a report can gap "
                     "straight through a stop.",
        sigbot_before="Ignored earnings dates.",
        verdict=REJECTED,
        evidence="Inverted: entries with earnings inside the hold returned "
                 "+2.265% vs +1.431% without (677 vs 6,130 entries). A "
                 "washed-out name reports against lowered expectations."),
    Behaviour(
        situation="Volatility explodes",
        professional="Steps aside when volatility goes vertical.",
        sigbot_before="No volatility ceiling; one 2020 stop sat 63% away.",
        verdict=REJECTED,
        evidence="Capping the stop width LOWERED expectancy (+1.247% uncapped "
                 "vs +0.26-0.64% capped) and made 2020 worse (-1.81% vs -7 to "
                 "-10%). In R the 15% cap looked best, but neighbouring caps "
                 "gave 0.047 / 0.061 / 0.039 / 0.032 R — not monotonic, the "
                 "practitioners' own sign of a tuned artefact. Risk sizing "
                 "already handles it: the account loses 1R however wide the "
                 "stop."),
    Behaviour(
        situation="A losing streak",
        professional="Cuts size after consecutive losses; never increases "
                     "to win it back.",
        sigbot_before="No reaction to its own results.",
        verdict=ADOPTED,
        evidence="The strongest result in the whole comparison. After four "
                 "straight losses the next trade returned -0.559 R and won "
                 "15.6% of the time; after three of four, -0.145 R; "
                 "otherwise +0.241 R and 69.0%. Losses arrive in clusters, "
                 "and outside the clusters the setup earns nearly six times "
                 "its +0.042 R average. CAVEAT: entries were ordered by date, "
                 "so four prior losses often means four names that fired on "
                 "the same crash day. A live pause triggers on CLOSED losses "
                 "days later, so the direction is certain and the magnitude "
                 "is overstated."),
)


def summary() -> str:
    """The comparison as a table a person can read."""
    lines = ["How an experienced trader responds, and whether it held here", ""]
    for verdict in (ADOPTED, REJECTED, UNTESTED):
        rows = [b for b in BEHAVIOURS if b.verdict == verdict]
        if not rows:
            continue
        lines.append(f"  {verdict} ({len(rows)})")
        for b in rows:
            lines.append(f"    {b.situation}")
            lines.append(f"      professional: {b.professional}")
            lines.append(f"      evidence:     {b.evidence}")
        lines.append("")
    adopted = sum(b.verdict == ADOPTED for b in BEHAVIOURS)
    rejected = sum(b.verdict == REJECTED for b in BEHAVIOURS)
    lines.append(f"  {adopted} adopted, {rejected} rejected on evidence. The "
                 "rejected ones are sound rules for trend-following; this "
                 "setup buys washouts, which is the opposite mechanism.")
    lines.append("  The honest size of the edge, in what reaches the account: "
                 "+0.042 R a trade, about +0.04% of capital at 1% risk. "
                 "Outside losing clusters it is +0.241 R, which is why the "
                 "streak pause matters more than any entry rule.")
    return "\n".join(lines)
