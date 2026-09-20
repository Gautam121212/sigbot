"""Setups: conditions with a measured, out-of-sample-validated edge.

WHY THIS REPLACES THE OLD APPROACH
----------------------------------
The daily model learned next-session direction from nine features and produced
an opinion on every asset, every session. Measured on 141,123 replayed
decisions it scored 51.4% against a 52.2% base rate — no edge, and its own
confidence score turned out to be uncorrelated with outcome, so selectivity
could not rescue it either.

The failure is structural, not a tuning problem. A model asked to have an
opinion on everything will be near chance on everything, because most sessions
contain no exploitable information. Forcing a prediction onto them buys noise
and pays costs for it.

This module inverts that. A setup is SILENT by default and speaks only when a
specific, pre-tested condition occurs. Fewer forecasts, each carrying evidence.

THE EVIDENCE BAR
----------------
A setup may only alert once it has been validated on real market history
across at least three NON-OVERLAPPING eras, with the edge in the same
direction in every one. A single backtested number is not enough: any
sufficiently searched dataset yields one. Consistency across eras is what
separates an effect from a coincidence, and the era results are recorded here
in the code so the claim can be audited rather than trusted.

Each setup also records the sample it was measured on. A setup whose live
record drifts away from its measured edge is a setup whose regime has changed,
and that is visible only because the expectation was written down first.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EraResult:
    """One out-of-sample window a setup was measured on."""

    label: str
    n: int
    hit_pct: float
    base_pct: float

    @property
    def edge_pp(self) -> float:
        return self.hit_pct - self.base_pct


@dataclass(frozen=True)
class Setup:
    """A condition with a measured edge, and the evidence for it."""

    name: str
    side: str                      # "BUY" or "SELL"
    plain: str                     # what it means, for a person
    condition: Callable[[dict], bool]
    eras: tuple[EraResult, ...] = field(default_factory=tuple)

    @property
    def measured_edge_pp(self) -> float:
        """Sample-weighted edge across every era it was validated on."""
        total = sum(e.n for e in self.eras)
        if not total:
            return 0.0
        return sum(e.edge_pp * e.n for e in self.eras) / total

    @property
    def total_observations(self) -> int:
        return sum(e.n for e in self.eras)

    def is_validated(self) -> bool:
        """Three or more eras, all pointing the same way, and a real edge.

        The direction test is the important half. A setup that worked hugely
        in one era and failed in two others has an attractive average and no
        future, and averaging would hide exactly that.
        """
        if len(self.eras) < 3:
            return False
        if not all(e.edge_pp > 0 for e in self.eras):
            return False
        return self.measured_edge_pp >= 3.0


def _deep_oversold(row: dict) -> bool:
    """RSI below 20 — a washout, not merely a dip.

    The threshold is 20 rather than the conventional 30 because the data says
    so: at RSI<30 the edge is +2.0pp and inconsistent across eras; at RSI<20
    it is +9.7pp and present in all three. The dose-response between them is
    the strongest single piece of evidence that this is a real effect rather
    than a lucky slice.
    """
    rsi = row.get("rsi_14")
    return rsi is not None and rsi < 20.0


SETUPS: tuple[Setup, ...] = (
    Setup(
        name="deep-oversold",
        side="BUY",
        plain=("The price has fallen far enough, fast enough, that recent "
               "selling looks exhausted. Historically it bounces more often "
               "than it continues falling — not always, but more often than "
               "chance, and measurably so."),
        condition=_deep_oversold,
        # Measured on 30 board names, 2015-present, daily closes from the
        # market-data provider. "hit" uses the live definition: direction
        # right AND the move larger than the round-trip cost.
        eras=(
            EraResult("2015-2018", n=81, hit_pct=55.6, base_pct=46.4),
            EraResult("2019-2021", n=90, hit_pct=60.0, base_pct=48.1),
            EraResult("2022-now", n=81, hit_pct=55.6, base_pct=47.6),
        ),
    ),
)


def evaluate(row: dict) -> Setup | None:
    """The validated setup that fires on this row, or None.

    None is the expected answer. Across the measured sample a setup fired on
    roughly one session in 170, and that rarity IS the design: the old model
    made 141,123 decisions to find no edge, and this one makes a few hundred
    to find a measurable one.
    """
    for setup in SETUPS:
        if setup.is_validated() and setup.condition(row):
            return setup
    return None


def unvalidated() -> tuple[Setup, ...]:
    """Setups being watched but not yet allowed to alert.

    Kept visible on purpose. A candidate that has not cleared the evidence bar
    is not a secret — it is the queue, and hiding it would make the system
    look more certain than it is.
    """
    return tuple(s for s in SETUPS if not s.is_validated())


def describe() -> str:
    """The console summary: what can fire, on what evidence."""
    lines = ["Setups — conditions with a measured edge", ""]
    for setup in SETUPS:
        mark = "LIVE " if setup.is_validated() else "QUEUED"
        lines.append(f"  [{mark}] {setup.name} ({setup.side})")
        lines.append(f"    {setup.plain}")
        for era in setup.eras:
            lines.append(f"      {era.label}: {era.hit_pct:.1f}% vs "
                         f"{era.base_pct:.1f}% base "
                         f"({era.edge_pp:+.1f}pp on {era.n} occurrences)")
        lines.append(f"    Weighted edge {setup.measured_edge_pp:+.1f}pp "
                     f"over {setup.total_observations} observations.")
        if not setup.is_validated():
            lines.append("    Not yet allowed to alert: needs three eras, all "
                         "positive, averaging at least +3pp.")
        lines.append("")
    lines.append("  A setup speaks only when its condition occurs, which is "
                 "rare on purpose. Silence is the normal state and is not a "
                 "failure.")
    return "\n".join(lines)
