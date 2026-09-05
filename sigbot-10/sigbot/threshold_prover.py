"""Threshold prover — reject impossible gates at design time.

This project once shipped a tier that could not fire. It asked for 40
observations and a 60% floor; at an observed 70% hit rate, 40 observations gives
a lower bound of 57.1%. The only way to trigger it was to move the gate down to
meet the evidence, which is the opposite of what a gate is for.

That was found by hand, months later. This module finds it in a test.

A threshold is **reachable** if some plausible observed rate produces a lower
bound at or above the gate within a sample you will actually collect. Two ways
it fails:

  unreachable   no observed rate clears the gate at that n. The tier is dead on
                arrival and its existence is misleading.
  vacuous       every observed rate clears it, including rates below the gate
                itself. The gate is decorative.

`prove()` returns the evidence either way: the minimum observed rate that works,
the sample it needs, and how long that takes at your actual rate of collection.
"""
from __future__ import annotations

from dataclasses import dataclass

from .stats import wilson_interval

MAX_N = 100_000


@dataclass(frozen=True)
class Proof:
    name: str
    min_n: int
    gate: float
    conf: float
    reachable: bool
    required_rate: float | None      # lowest observed rate that clears the gate
    n_for_plausible: int | None      # sample needed at a plausible rate
    plausible_rate: float
    note: str

    def render(self) -> str:
        head = f"{self.name}: n>={self.min_n}, gate {self.gate:.0%} at {self.conf:.0%} confidence"
        return f"{head}\n  {'REACHABLE' if self.reachable else 'UNREACHABLE'} — {self.note}"

    def years_at(self, observations_per_day: float) -> float | None:
        if not self.reachable or not self.n_for_plausible or observations_per_day <= 0:
            return None
        return self.n_for_plausible / observations_per_day / 365.0


def required_rate(min_n: int, gate: float, conf: float = 0.90) -> float | None:
    """Lowest observed hit rate whose lower bound clears `gate` at `min_n`.

    None when even a perfect record fails, which means the gate is unreachable
    at that sample size however well the thing performs.
    """
    if min_n <= 0 or not 0 < gate < 1:
        return None
    if wilson_interval(min_n, min_n, conf)[0] < gate:
        return None                      # a perfect record still misses
    lo_k, hi_k = 0, min_n
    while lo_k < hi_k:                   # smallest k whose bound clears the gate
        mid = (lo_k + hi_k) // 2
        if wilson_interval(mid, min_n, conf)[0] >= gate:
            hi_k = mid
        else:
            lo_k = mid + 1
    return lo_k / min_n


def sample_for(rate: float, gate: float, conf: float = 0.90) -> int | None:
    """Smallest n at which `rate` produces a lower bound clearing `gate`."""
    if not 0 < rate <= 1 or not 0 < gate < 1 or rate <= gate:
        return None                      # a rate at or below the gate never clears it
    n = 2
    while n <= MAX_N:
        if wilson_interval(round(rate * n), n, conf)[0] >= gate:
            return n
        n = n + 1 if n < 200 else int(n * 1.15)
    return None


def prove(name: str, min_n: int, gate: float, conf: float = 0.90,
          plausible_margin: float = 0.10) -> Proof:
    """Check a threshold before it ships.

    `plausible_margin` is how far above the gate a real system might actually
    perform. Ten points is deliberately generous: if a tier needs more than that
    to become reachable, it is asking for a level of skill nothing here has
    demonstrated.
    """
    plausible = min(0.99, gate + plausible_margin)
    need = required_rate(min_n, gate, conf)
    n_needed = sample_for(plausible, gate, conf)

    # `min_n` is a floor, not the sample the tier is judged at: an asset clears
    # the tier at any n at or above it. So the question is whether ANY sample a
    # plausible performer would reach clears the gate — not whether exactly
    # min_n does. Asking the narrower question flagged four working tiers on the
    # first run of this module.
    if n_needed is None:
        return Proof(name, min_n, gate, conf, False, need, None, plausible,
                     f"no sample size lets a {plausible:.0%} performer clear a "
                     f"{gate:.0%} gate. The tier cannot fire.")

    # A gate that a record exactly at the gate already clears is not gating.
    if wilson_interval(round(gate * min_n), min_n, conf)[0] >= gate:
        return Proof(name, min_n, gate, conf, False, need, n_needed, plausible,
                     f"a record exactly at the gate ({gate:.0%}) already clears it "
                     f"at n={min_n}. The gate is decorative — raise it, or raise "
                     "the sample.")

    if n_needed > min_n:
        return Proof(name, min_n, gate, conf, True, need, n_needed, plausible,
                     f"reachable, but the floor of {min_n} is not what binds: a "
                     f"{plausible:.0%} performer needs n>={n_needed}. Assets will "
                     f"clear it around there, not at {min_n}.")

    return Proof(name, min_n, gate, conf, True, need, n_needed, plausible,
                 f"a {plausible:.0%} performer clears it by n={n_needed}, within "
                 f"the {min_n} floor."
                 + (f" At exactly {min_n} it needs {need:.0%}." if need else ""))


def prove_all() -> list[Proof]:
    """Every live threshold in the system, checked."""
    from .tiers import TIER_RULES
    from .watchlist import RULES

    out = [prove(f"tier {r.tier.value}", r.min_observations, r.min_lower_bound)
           for r in TIER_RULES]
    out.append(prove("board GREEN", RULES.green_min_n, RULES.green_min_lower,
                     RULES.conf))
    out.append(prove("board AMBER", RULES.amber_min_n, RULES.amber_min_lower,
                     RULES.conf))
    return out


def report() -> str:
    proofs = prove_all()
    bad = [p for p in proofs if not p.reachable]
    lines = [p.render() for p in proofs]
    lines.append("")
    lines.append("All thresholds are reachable." if not bad else
                 f"{len(bad)} threshold(s) cannot fire as configured.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    print(report())
    sys.exit(0 if all(p.reachable for p in prove_all()) else 1)
