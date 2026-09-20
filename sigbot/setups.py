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
    """RSI below 20, but only while money flow has NOT also collapsed.

    RSI<20 is the washout. The threshold is 20 rather than the conventional 30
    because the data says so: at RSI<30 the edge is small and inconsistent
    across eras, at RSI<20 it is present in all three, and the dose-response
    between them is the strongest evidence the effect is real.

    The MFI condition is the half that took a wide search to find, and it is a
    veto that genuinely works — unlike the per-name personality veto, which
    sounded just as sensible and tested flat. Across 3.5 million sessions:

        MFI < 10 alone                39.1%   (8.4pp BELOW a 47.5% baseline)
        RSI<20 combined with MFI<10   41.3%
        RSI<20 with MFI >= 10         52.5%

    Money-flow exhaustion is not the same event as price exhaustion. When both
    collapse together the selling has conviction behind it and the fall tends
    to continue; when price is washed out but money flow is not, it tends to
    be bought. Combining them without checking would have kept the worst
    quarter of the sample and cut the edge by more than half.
    """
    rsi, mfi = row.get("rsi_14"), row.get("mfi_14")
    if rsi is None or rsi >= 20.0:
        return False
    # Missing MFI is treated as disqualifying. The veto removes the worst
    # cell in the sample, so failing open would reinstate exactly what it
    # exists to exclude.
    return mfi is not None and mfi >= 10.0


SETUPS: tuple[Setup, ...] = (
    Setup(
        name="deep-oversold",
        side="BUY",
        plain=("The price has fallen far enough, fast enough, that recent "
               "selling looks exhausted — but money has not fled the name "
               "with it. That second half matters: when both give way "
               "together the fall usually continues. Historically this "
               "combination bounces more often than chance, measurably so, "
               "in every period tested."),
        condition=_deep_oversold,
        # Measured across the FULL US large-cap universe (market cap > $2bn,
        # common stock, US-domiciled) over 3.5 million sessions, not the 30
        # board names an earlier version used. That matters: on 30 names the
        # best-looking context cell scored 72.7% on 22 occurrences, and the
        # same cell across the full universe scores 51.3% on 1,633. The small
        # sample was noise wearing the shape of a discovery.
        #
        # "hit" uses the live definition: direction right AND the move larger
        # than the round-trip cost.
        eras=(
            EraResult("2016-2019", n=3224, hit_pct=50.0, base_pct=47.6),
            EraResult("2020-2022", n=3037, hit_pct=55.8, base_pct=47.5),
            EraResult("2023-now", n=3017, hit_pct=51.9, base_pct=47.5),
        ),
    ),
)


def evaluate(row: dict, profile=None) -> Setup | None:
    """The validated setup that fires on this row, or None.

    None is the expected answer. Across the measured sample a setup fired on
    roughly one session in 170, and that rarity IS the design: the old model
    made 141,123 decisions to find no edge, and this one makes a few hundred
    to find a measurable one.

    `profile` is the asset's own behavioural record. A setup validated across
    a pooled universe still has to survive the name it is about to fire on:
    the same washout gets bought in one stock and keeps falling in another,
    and that difference persisted across a decade. Passing None skips the
    check, which is right when the history is not available but is never the
    preferred path.
    """
    from .personality import veto

    for setup in SETUPS:
        if not (setup.is_validated() and setup.condition(row)):
            continue
        if veto(profile, setup.side):
            continue
        return setup
    return None


def context_multiplier(row: dict) -> tuple[float, str]:
    """How much the surrounding conditions favour this setup, and why.

    Measured, not assumed. Splitting deep-oversold days by trend, volume and
    volatility gave a spread from 51% to 73%, and the strongest cell was
    capitulation — a volume spike in an otherwise calm name, which is what
    forced selling looks like when it finishes. The weakest was a volume spike
    in an already-violent name, which is what forced selling looks like when
    it is still going.

    Returned as a weight rather than a filter because the sample in the best
    cell was 22 occurrences. That is enough to lean on and nowhere near enough
    to gate on, and treating it as a gate would be the same overreach as
    trusting any single backtested slice.
    """
    close = row.get("close") or 0.0
    atr = row.get("atr_14")
    volume = row.get("volume")
    vol_ma = row.get("volume_ma_20")

    calm = atr is not None and close > 0 and (atr / close) <= 0.04
    spike = volume is not None and vol_ma and volume > vol_ma * 1.5

    if calm and spike:
        return 1.5, ("Looks like capitulation: a burst of selling in a name "
                     "that is not normally this volatile. Historically the "
                     "strongest version of this setup.")
    if not calm and spike:
        return 0.6, ("Heavy selling in an already-volatile name. Historically "
                     "the weakest version — the fall often is not finished.")
    if calm:
        return 1.2, "A quiet name that has fallen hard. A clean version."
    return 1.0, "Ordinary conditions for this setup."


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


# Candidates tested on real history and REJECTED. Kept so they are not
# rediscovered and re-shipped by someone who only sees the pooled number.
REJECTED = (
    ("gap down > 5%",
     "Pooled 53.6% on 24,097 occurrences — the best raw number in the entire "
     "search. Split by era: -3.2pp (2016-19), +15.0pp (2020-22), -0.4pp "
     "(2023-now). The whole edge is one extraordinary period, and a signal "
     "that only worked during the 2020 crash and recovery is a description of "
     "that crash, not a rule for the future."),
    ("day down > 8%",
     "52.9% pooled on 31,831, and fails the same way for the same reason — "
     "it is largely the same days as the gap-down set."),
    ("per-name bounce personality as a veto",
     "Removed 87 of 252 occurrences and moved the hit rate 57.1% -> 57.0%. "
     "The profile measures bounce after an ORDINARY down day; the setup fires "
     "on a DEEP washout. A disposition measured on one condition does not "
     "transfer to another."),
    ("capitulation context (calm name, volume spike)",
     "72.7% on 22 occurrences across 30 names. Across the full universe the "
     "same cell is 51.3% on 1,633. A 22-row cell is not a finding."),
    ("MFI < 10 as an entry",
     "39.1% — 8.4pp BELOW baseline on 12,633 occurrences. Inverted, and "
     "strongly enough that it became the veto above instead."),
    ("Stochastic K < 5, hammer candles, Williams %R < -95, CCI < -250, "
     "25% below the 200-day average, closing at the day's low",
     "All within 2pp of the 47.5% baseline on large samples. Not edges."),
)


def rejected_summary() -> str:
    """What was tried and did not survive. The queue's other half."""
    lines = ["Tested and rejected", ""]
    for name, why in REJECTED:
        lines.append(f"  {name}")
        lines.append(f"    {why}")
        lines.append("")
    lines.append("  Recorded on purpose. A filter with an attractive pooled "
                 "number and no era consistency is the single easiest way to "
                 "ship a backtest as a strategy.")
    return "\n".join(lines)
