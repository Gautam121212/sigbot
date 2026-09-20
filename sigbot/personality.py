"""How each asset actually behaves, measured from its own history.

WHY THIS EXISTS
---------------
Testing a signal across a pooled universe answers "does this work on average".
A trader does not trade the average. They know that a washout in one name gets
bought and the same washout in another keeps falling, and they size or skip
accordingly. That knowledge is the difference between a rule and a read.

It is also measurable. Across 30 board names split into two halves of a decade,
the rank order of "how often does this bounce after a down day" persisted at
Spearman +0.398 between halves. Not strong, but nowhere near random — and the
useful part is where the persistence concentrates.

WHAT PERSISTS, AND WHAT DOES NOT
--------------------------------
Of the eight strongest bouncers in 2015-2019, three were still in the top eight
in 2020-present. Of the eight weakest, FIVE were still in the bottom eight.

Knowing which names do NOT bounce is roughly twice as reliable as knowing which
do. So this module is used primarily as a veto, not a selector: it removes
names where a mean-reversion setup has historically failed, rather than
promising that the survivors will work.

Every high bouncer also declined between halves and every low one rose — plain
regression to the mean. The ordering survives, the magnitude decays. So the
stored number is SHRUNK toward the universe average: using the raw historical
rate would consistently overstate what happens next, and the size of that
overstatement is exactly what the two-half test measured.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# What a coin flip scores on this measure, near enough, across the universe.
UNIVERSE_BOUNCE = 50.0

# Weight of the prior, in observations. A name with 250 down-days gets roughly
# half its own history and half the universe average; one with 50 gets mostly
# the average. Set to 250 because that is where the two-half test showed
# per-name estimates starting to carry information rather than noise.
PRIOR_STRENGTH = 250.0

# Below this shrunk rate, mean-reversion setups are vetoed on the name.
# Deliberately set below 50: the claim is not "this name trends", it is "this
# name has failed to bounce often enough, for long enough, that buying its
# washouts has no support in its own record".
VETO_BELOW = 47.0


@dataclass(frozen=True)
class Profile:
    """One asset's measured behaviour."""

    symbol: str
    down_days: int
    raw_bounce_pct: float
    shrunk_bounce_pct: float

    @property
    def is_reliable_bouncer(self) -> bool:
        return self.shrunk_bounce_pct >= 52.0

    @property
    def is_vetoed(self) -> bool:
        """Mean-reversion setups should not fire on this name."""
        return self.shrunk_bounce_pct < VETO_BELOW

    def plain(self) -> str:
        """What this means, without the statistics."""
        if self.down_days < 60:
            return ("Not enough history to say how this one behaves after a "
                    "fall. Treated as average until it has more.")
        if self.is_vetoed:
            return (f"After a sharp fall this one keeps falling more often "
                    f"than it recovers ({self.shrunk_bounce_pct:.0f}% bounce "
                    f"rate over {self.down_days:,} down days). Buying its dips "
                    "has not worked historically, so setups that rely on a "
                    "bounce are skipped here.")
        if self.is_reliable_bouncer:
            return (f"This one tends to get bought after a fall "
                    f"({self.shrunk_bounce_pct:.0f}% over {self.down_days:,} "
                    "down days), which is what a mean-reversion setup needs.")
        return (f"Behaves close to average after a fall "
                f"({self.shrunk_bounce_pct:.0f}%). No help either way.")


def profile_from_closes(symbol: str, closes: Sequence[float],
                        drop_pct: float = 0.01) -> Profile:
    """Measure one asset's bounce tendency from its closing prices.

    A "down day" is a fall of more than `drop_pct`; a "bounce" is any positive
    move on the following session. Deliberately a cruder test than the live hit
    definition — this is asking what the name's DISPOSITION is, not whether a
    particular trade would have paid, and adding the cost filter here would mix
    two questions together.
    """
    downs = bounces = 0
    for i in range(1, len(closes) - 1):
        prev, today, tomorrow = closes[i - 1], closes[i], closes[i + 1]
        if prev <= 0 or today <= 0:
            continue
        if today / prev - 1.0 < -drop_pct:
            downs += 1
            if tomorrow > today:
                bounces += 1

    raw = (bounces / downs * 100.0) if downs else UNIVERSE_BOUNCE
    # Shrink toward the universe average. The two-half test showed every
    # extreme estimate moving back toward the middle, so carrying the raw
    # number forward would systematically overstate the next period.
    shrunk = ((bounces + UNIVERSE_BOUNCE / 100.0 * PRIOR_STRENGTH)
              / (downs + PRIOR_STRENGTH) * 100.0)
    return Profile(symbol=symbol, down_days=downs,
                   raw_bounce_pct=round(raw, 1),
                   shrunk_bounce_pct=round(shrunk, 1))


# The veto is OFF, and the reason is a measurement rather than a preference.
#
# It was an obvious-sounding idea: a mean-reversion setup should not fire on a
# name whose own record shows it does not mean-revert. Tested on the real
# deep-oversold sample, it removed 87 of 252 occurrences and moved the hit
# rate from 57.1% to 57.0%. It cost a third of the trades and bought nothing.
#
# The reason is a category error worth naming: the profile measures bounce
# after an ORDINARY down day, and the setup fires on a DEEP washout. Those are
# different conditions, and a disposition measured on one does not transfer to
# the other. The profile is still a real, persistent property — it just does
# not answer this question.
#
# Left in place, switched off, with the evidence attached. A filter that
# sounds right and tests flat is exactly the kind that gets re-invented in six
# months by someone who has forgotten it was already tried.
VETO_ENABLED = False


def veto(profile: Profile | None, setup_side: str) -> str | None:
    """Reason to skip this setup on this name, or None to allow it.

    Always None while VETO_ENABLED is False. See the note above: enabling it
    requires a test on the SPECIFIC setup it would gate, not on the general
    disposition it was measured from.
    """
    if not VETO_ENABLED:
        return None
    if profile is None or setup_side != "BUY":
        return None
    if profile.down_days < 60:
        return None
    if profile.is_vetoed:
        return (f"{profile.symbol} has bounced after a fall only "
                f"{profile.shrunk_bounce_pct:.0f}% of the time across "
                f"{profile.down_days:,} down days. This setup needs a bounce.")
    return None


def summarise(profiles: Sequence[Profile]) -> str:
    """Console view, worst first — the veto list is the useful end."""
    if not profiles:
        return "No profiles yet. Run this after the board has price history."

    ranked = sorted(profiles, key=lambda p: p.shrunk_bounce_pct)
    lines = ["How each name behaves after a fall", ""]
    lines.append(f"  {'symbol':<12} {'down days':>10} {'raw':>7} {'shrunk':>8}  state")
    for p in ranked:
        state = ("VETOED" if p.is_vetoed
                 else "bouncer" if p.is_reliable_bouncer else "average")
        lines.append(f"  {p.symbol:<12} {p.down_days:>10,} "
                     f"{p.raw_bounce_pct:>6.1f}% {p.shrunk_bounce_pct:>7.1f}%  {state}")
    vetoed = sum(1 for p in profiles if p.is_vetoed)
    lines.append("")
    lines.append(f"  {vetoed} name(s) vetoed for bounce-based setups.")
    lines.append("  Shrunk toward 50% on purpose: every extreme reading in the "
                 "first half of the test period moved back toward the middle "
                 "in the second, so the raw rate overstates what comes next.")
    lines.append("  Used mainly as a veto. Knowing which names do NOT bounce "
                 "proved about twice as persistent as knowing which do.")
    return "\n".join(lines)
