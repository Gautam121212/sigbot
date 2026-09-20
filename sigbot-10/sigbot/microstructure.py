"""Microstructure signal specs, with mandatory attestation.

Some of the effects proposed for this system are real. PEAD is one of the most
studied anomalies in finance. But a claimed edge attaches to a *mechanism*, and
a mechanism only transfers to your system if your detector actually observes
it. Three of the five proposed detectors do not:

    claimed mechanism            detector proposed                observes it?
    ------------------------------------------------------------------------
    post-earnings drift          gap >3% on >2.5x volume          NO - no earnings calendar
    perpetual funding extreme    RSI > 85 + volume spike          NO - RSI is a price
                                                                  oscillator, not funding
    index inclusion forced bid   volume spike + near 52wk high    NO - inclusions are
                                                                  announced, not inferred
    VIX spike reversion          VIX > 35 and > 2x 20d avg        YES
    macro first-bar momentum     first 5m bar after 8:30 ET       PARTIAL - needs a
                                                                  release calendar

When the detector does not observe the mechanism, the claimed hit rate belongs
to a different signal. Carrying it across is how an unsourced "78%" ends up
attached to an RSI threshold.

Two other problems the specs below make visible:

**PEAD is not a 30-60 minute effect.** It is a multi-month drift in
cross-sectional abnormal returns, and it has attenuated: hedge returns fell
from roughly 5% per quarter in the 1980s-90s to around 4% in the 2000s and 3%
or lower by the late 2010s. An intraday reading of PEAD is not the documented
anomaly under a shorter clock; it is a different claim with no cited support.

**A signal whose trigger sits inside a blocked regime can never fire.** The
proposed design blocks all signals when VIX > 35 and defines a signal that
fires when VIX > 35. `validate_signal_set` raises on that rather than letting
it sit dead in production.

## The rule this module enforces

No signal carries a prior hit rate. Ever. `claimed_hit_rate` is stored as a
claim to be tested and is rendered next to the observed rate so the gap is
visible. Every signal enters the pattern registry at DISCOVERY with n=0 and
earns its number the same way everything else does.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Observability(str, Enum):
    DIRECT = "DIRECT"        # the detector measures the mechanism itself
    PARTIAL = "PARTIAL"      # measures it, but incompletely
    PROXY = "PROXY"          # measures something else and hopes it correlates

    @property
    def may_cite_claim(self) -> bool:
        """Only a direct detector may even display an external claim."""
        return self is Observability.DIRECT


@dataclass(frozen=True)
class SignalSpec:
    key: str
    mechanism: str                   # what is claimed to produce the edge
    required_observable: str         # what you must measure to see that mechanism
    detector: str                    # what the code actually measures
    observability: Observability
    claimed_hit_rate: float | None = None
    claim_source: str | None = None  # a citation, or None
    horizon_hours: float = 24.0
    trigger_regimes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.claimed_hit_rate is not None and not self.claim_source:
            raise ValueError(
                f"{self.key}: a claimed hit rate without a source is not a claim, "
                "it is a number. Provide claim_source or set claimed_hit_rate=None."
            )

    @property
    def prior_hit_rate(self) -> None:
        """Always None. No signal starts with evidence it did not earn here."""
        return None

    def render(self, observed_n: int = 0, observed_rate: float | None = None,
               observed_lower: float | None = None) -> str:
        lines = [f"{self.key}  [{self.observability.value}]",
                 f"  mechanism: {self.mechanism}",
                 f"  needs to observe: {self.required_observable}",
                 f"  actually measures: {self.detector}"]
        if self.observability is not Observability.DIRECT:
            lines.append(
                "  WARNING: the detector does not observe the mechanism. Any external "
                "hit rate for this effect describes a different signal."
            )
        if self.claimed_hit_rate is not None and self.observability.may_cite_claim:
            lines.append(f"  external claim: {self.claimed_hit_rate:.0%} "
                         f"(source: {self.claim_source})")
        if observed_n == 0:
            lines.append("  observed here: 0 resolved observations. Not alertable.")
        else:
            lines.append(
                f"  observed here: {observed_n} resolved, {observed_rate:.1%}, "
                f"90% lower bound {observed_lower:.1%}"
            )
        return "\n".join(lines)


# The five proposed effects, specified honestly. Note that not one carries a
# claimed_hit_rate: none of the figures offered (72%, 78%, 76%, 77%, 71%, with
# event counts) came with a citation, and an uncited number cannot be stored.
SPECS: tuple[SignalSpec, ...] = (
    SignalSpec(
        key="pead_gap_proxy",
        mechanism="institutions reprice slowly after an earnings surprise, producing "
                  "drift in the surprise direction",
        required_observable="an earnings calendar plus a surprise measure (SUE or "
                            "consensus-vs-actual)",
        detector="gap > 3% on > 2.5x average volume",
        observability=Observability.PROXY,
        horizon_hours=24.0,
    ),
    SignalSpec(
        key="crypto_leverage_proxy",
        mechanism="perpetual funding at an extreme means the book is over-leveraged "
                  "one way and mean-reverts as positions liquidate",
        required_observable="perpetual funding rate and open interest from the venue",
        detector="RSI > 85 plus a volume spike",
        observability=Observability.PROXY,
        horizon_hours=12.0,
    ),
    SignalSpec(
        key="index_inclusion_proxy",
        mechanism="index funds are mandated to buy an added name on the rebalance "
                  "date, creating forced demand",
        required_observable="the index provider's announced add/delete list and "
                            "effective date",
        detector="volume spike plus price near 52-week highs",
        observability=Observability.PROXY,
        horizon_hours=24.0,
    ),
    SignalSpec(
        key="vix_spike_reversion",
        mechanism="extreme implied volatility reflects transient panic pricing and "
                  "decays",
        required_observable="the VIX level and its trailing average",
        detector="VIX > 35 and > 2x the 20-day average",
        observability=Observability.DIRECT,
        horizon_hours=48.0,
        trigger_regimes=frozenset({"vix_above_35"}),
    ),
    SignalSpec(
        key="macro_first_bar",
        mechanism="informed traders set the initial direction on a scheduled release "
                  "and less-informed flow follows",
        required_observable="an economic release calendar plus intraday bars",
        detector="first 5-minute bar after 13:30 UTC on > 3x average volume",
        observability=Observability.PARTIAL,
        horizon_hours=0.5,
    ),
)


def validate_signal_set(specs, blocked_regimes: set[str]) -> None:
    """Raise if any signal can only fire inside a regime the filter blocks.

    The proposed design blocks everything when VIX > 35 and defines a signal
    that requires VIX > 35. That is not a conservative filter; it is a signal
    that silently never fires while still appearing in the strategy table.
    """
    for spec in specs:
        dead = spec.trigger_regimes & blocked_regimes
        if dead:
            raise ValueError(
                f"{spec.key} triggers only in {sorted(dead)}, which the regime "
                f"filter blocks. Either the signal or the filter must go — "
                "shipping both means the signal can never fire."
            )


def proxy_signals(specs=SPECS) -> list[SignalSpec]:
    return [s for s in specs if s.observability is Observability.PROXY]
