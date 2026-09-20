"""Scan wide, speak narrow, and take labelled risk.

THE PROBLEM WITH THE FIXED BOARD
--------------------------------
Every model ran on the same 100 names. That is a narrow window on a market of
thousands, and it caps learning twice over: a setup can only be observed where
the board happens to be looking, and the board only rotates on evidence it
gathered from the same narrow window. It cannot find what it is not watching.

So the stocks scan does not use the board. It sweeps the whole universe and
reports only the names where something fired. The output length is whatever
the market produced that day — some days none, some days thirty. That is the
correct behaviour for a scanner and it is not a failure when it is quiet.

THE PROBLEM WITH ONLY TRADING CERTAINTY
---------------------------------------
A gate that admits only fully validated setups is safe and nearly useless. It
fires rarely, gathers little, and therefore never validates anything new — the
evidence bar becomes a wall around the one setup that happened to clear it
first. A trader does not work that way: they take a size they can afford on a
read they believe but cannot prove, and they find out.

So there are two tiers, and the second one is the learning mechanism:

  PROVEN  A setup validated across three separate eras, all positive.
          This is what the paper book sizes normally.

  RISKY   A condition with a positive measured edge that has NOT cleared the
          era test — thin sample, or one bad period, or simply new. Labelled
          risky everywhere it appears, sized small, and traded on paper
          precisely so it accumulates the record that would promote or kill
          it.

The label is the honesty. A risky row is never dressed as a proven one, and a
proven one is never quietly relaxed to let more through.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

PROVEN = "PROVEN"
RISKY = "RISKY"


@dataclass(frozen=True)
class Candidate:
    """A condition worth trading small while it earns its record.

    `pooled_edge_pp` and `pooled_n` are what the wide historical sweep
    measured. `eras_positive` is how many of the three test periods it was
    positive in — the number that decides whether it can ever be promoted.
    """

    name: str
    side: str
    plain: str
    condition: Callable[[dict], bool]
    pooled_edge_pp: float
    pooled_n: int
    eras_positive: int

    @property
    def conviction_pct(self) -> float:
        """0-100: how much of the evidence bar this has actually cleared.

        Two thirds of it is era consistency, because that is what separated
        every real finding from every false one in the sweep: the best raw
        number in the entire search (gap-down, 53.6% on 24,097) was positive
        in one era out of three. Sample size and edge size together carry the
        remaining third — they are necessary, and on their own they lie.
        """
        era_part = min(self.eras_positive / 3.0, 1.0) * 66.0
        size_part = min(self.pooled_n / 5000.0, 1.0) * 17.0
        edge_part = min(max(self.pooled_edge_pp, 0.0) / 5.0, 1.0) * 17.0
        return round(era_part + size_part + edge_part, 1)


def _oversold_money_holding(row: dict) -> bool:
    """The proven one: price washed out, money flow not."""
    rsi, mfi = row.get("rsi_14"), row.get("mfi_14")
    return (rsi is not None and rsi < 20.0
            and mfi is not None and mfi >= 10.0)


def _stretched_below_trend(row: dict) -> bool:
    """25% or more below the 200-day average — 49.2% on 204,051 sessions."""
    close, sma = row.get("close"), row.get("sma_200")
    return bool(close and sma and close < sma * 0.75)


def _extreme_williams(row: dict) -> bool:
    """Williams %R under -95 — 49.0% on 176,816 sessions."""
    w = row.get("willr_14")
    return w is not None and w < -95.0


def _hard_down_day(row: dict) -> bool:
    """Down more than 8% in a session — 52.9% pooled, but only 2 eras positive."""
    close, prev = row.get("close"), row.get("prev_close")
    return bool(close and prev and prev > 0 and close / prev - 1.0 < -0.08)


# Everything below was measured on the full US large-cap universe, 2016-present,
# roughly 3.5 million sessions, against a 47.5% baseline. The edge figures are
# pooled; `eras_positive` is what actually decides promotion.
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        name="oversold-money-holding", side="BUY",
        plain=("Price has been hammered but money has not left the name. "
               "Historically the strongest version of a bounce setup."),
        condition=_oversold_money_holding,
        pooled_edge_pp=5.0, pooled_n=9278, eras_positive=3),
    Candidate(
        name="hard-down-day", side="BUY",
        plain=("Down more than 8% in one session. Often overdone — but the "
               "edge leans heavily on 2020-22, so this one is unproven."),
        condition=_hard_down_day,
        pooled_edge_pp=5.4, pooled_n=31831, eras_positive=2),
    Candidate(
        name="stretched-below-trend", side="BUY",
        plain=("A quarter or more below its own one-year average. A long way "
               "from home, which sometimes means a snap back."),
        condition=_stretched_below_trend,
        pooled_edge_pp=1.7, pooled_n=204051, eras_positive=2),
    Candidate(
        name="extreme-williams", side="BUY",
        plain=("Closed at the very bottom of its recent range. A weak signal "
               "on its own, kept to see whether it adds anything."),
        condition=_extreme_williams,
        pooled_edge_pp=1.5, pooled_n=176816, eras_positive=2),
)


@dataclass(frozen=True)
class Hit:
    """One name the scan wants to show, with its tier and why."""

    symbol: str
    candidate: Candidate
    tier: str
    conviction_pct: float
    context_weight: float
    reason: str

    @property
    def colour(self) -> str:
        return "var(--green)" if self.tier == PROVEN else "var(--faint)"

    @property
    def label(self) -> str:
        return ("Worth acting on" if self.tier == PROVEN
                else "Risky — unproven")


def tier_of(candidate: Candidate) -> str:
    """Proven only on three positive eras AND a real edge.

    Both halves are required. Three positive eras on +0.3pp is consistency
    without profit; +15pp in one era out of three is the gap-down trap.
    """
    if candidate.eras_positive >= 3 and candidate.pooled_edge_pp >= 3.0:
        return PROVEN
    return RISKY


def scan_row(symbol: str, row: dict) -> Hit | None:
    """The strongest condition firing on this name, or None.

    Proven candidates are preferred over risky ones when both fire, so a name
    is never labelled risky if there is a proven reason to hold it.
    """
    from .setups import context_multiplier

    firing = [c for c in CANDIDATES if c.condition(row)]
    if not firing:
        return None

    firing.sort(key=lambda c: (tier_of(c) != PROVEN, -c.conviction_pct))
    best = firing[0]
    weight, why = context_multiplier(row)
    return Hit(symbol=symbol, candidate=best, tier=tier_of(best),
               conviction_pct=best.conviction_pct, context_weight=weight,
               reason=why)


def position_size(hit: Hit, base_size: float) -> float:
    """What a paper position in this name should be worth.

    A risky read is taken at a third of normal size. That is the whole reason
    the risky tier can exist at all: the cost of being wrong on an unproven
    condition is bounded in advance, so the system can afford to find out
    rather than refusing to look.
    """
    size = base_size * (1.0 if hit.tier == PROVEN else 0.33)
    return round(size * hit.context_weight, 2)


def summarise(hits: Sequence[Hit], looked: int) -> str:
    """The console view: what fired, in which tier, out of how many looked at."""
    if not hits:
        return (f"Looked at {looked:,} name(s). Nothing fired. That is the "
                "usual outcome and costs nothing — the scan is wide so that "
                "the rare days are not missed, not so that every day "
                "produces something.")

    proven = [h for h in hits if h.tier == PROVEN]
    risky = [h for h in hits if h.tier == RISKY]
    lines = [f"Scanned {looked:,} name(s); {len(hits)} fired.", ""]
    for group, title in ((proven, "Worth acting on"), (risky, "Risky — unproven")):
        if not group:
            continue
        lines.append(f"  {title} ({len(group)})")
        for h in sorted(group, key=lambda x: -x.conviction_pct):
            lines.append(f"    {h.symbol:<10} {h.candidate.name:<24} "
                         f"conviction {h.conviction_pct:.0f}%  "
                         f"size x{h.context_weight:.1f}")
        lines.append("")
    if risky:
        lines.append("  Risky rows are traded on paper at a third of normal "
                     "size. They are there to earn a record, not because they "
                     "are believed — a gate that only admits certainty never "
                     "learns anything new.")
    return "\n".join(lines)
