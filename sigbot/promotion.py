"""The promotion ladder: what a strategy must prove before real money follows it.

HOW PROFESSIONALS DO THIS
-------------------------
Trading firms do not switch a strategy from paper to full size. They run it
on paper, then with a tiny real allocation (an "incubation" or pilot stage)
to measure what paper cannot — real fills, real slippage, real behaviour
under their own nerves — then at limited size, and only then at full size.
Every step up needs evidence; every step down happens automatically when the
evidence turns.

    PAPER        signals recorded and replayed; no money
    PILOT        real orders at a tenth of normal risk (0.1% a trade)
    LIMITED      real orders at half risk (0.5% a trade)
    FULL         real orders at normal risk (1% a trade)

WHAT THIS MODULE DOES AND DOES NOT DO
-------------------------------------
It EVALUATES. It reports which stage the evidence supports and exactly which
criteria are blocking the next one. It never places an order: there is no
broker connection anywhere in sigbot, and `LIVE_EXECUTION_ENABLED` is a
constant, not a setting. Turning on real trading must be a deliberate human
change to code — building an execution layer, reviewing it, and flipping that
constant — never something a passing test or a good month can do by itself.

Today every criterion that can be measured says the same thing: on fair
historical data, net of costs, the strategies trailed simply holding the
index. So the honest current stage is PAPER, and the ladder says why.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence

# Deliberately a constant. See the module docstring.
LIVE_EXECUTION_ENABLED = False

PAPER, PILOT, LIMITED, FULL = "PAPER", "PILOT", "LIMITED", "FULL"
STAGES = (PAPER, PILOT, LIMITED, FULL)
RISK_PER_TRADE = {PAPER: 0.0, PILOT: 0.001, LIMITED: 0.005, FULL: 0.01}

# Evidence required to leave PAPER. Each is the kind of bar a professional
# allocator applies before a strategy gets its first real dollar.
MIN_PAPER_TRADES = 120          # about ten months at twelve trades a month
MIN_PAPER_MONTHS = 6
MIN_T_STAT = 2.0                # live R reliably above zero, not luck
MAX_PAPER_DRAWDOWN = 0.15

# Each live stage must hold for this many months before the next.
MONTHS_AT_STAGE = {PILOT: 3, LIMITED: 6}
# Real costs may exceed the modelled ones by at most this factor.
MAX_SLIPPAGE_RATIO = 1.5


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Evidence:
    """Everything the ladder judges, gathered in one place."""
    hist_net_month: float          # fair history, net of costs
    index_month: float             # buy-and-hold over the same period
    oos_net_month: float           # the years never used to choose
    paper_r: Sequence[float]       # live paper trades, in R
    paper_months: Sequence[float]  # live paper monthly returns
    paper_drawdown: float          # worst peak-to-trough, as a fraction
    review_drifts: int             # principles DRIFTING in the monthly review
    stage: str = PAPER
    months_at_stage: int = 0
    live_months: Sequence[float] = ()
    slippage_ratio: float | None = None   # real cost / modelled cost


def t_stat(values: Sequence[float]) -> float:
    """How many standard errors the mean sits above zero."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean / sqrt(var / n) if var > 0 else 0.0


def paper_to_pilot(ev: Evidence) -> list[Criterion]:
    """What must be true before any real money, even a tenth of normal risk."""
    months = list(ev.paper_months)
    avg = sum(months) / len(months) if months else 0.0
    t = t_stat(ev.paper_r)
    return [
        Criterion("Fair history beats holding the index",
                  ev.hist_net_month > ev.index_month,
                  f"{ev.hist_net_month * 100:+.2f}% a month net, against "
                  f"{ev.index_month * 100:+.2f}% for the index"),
        Criterion("Unseen years added return beyond the index",
                  ev.oos_net_month > 0.002,
                  f"{ev.oos_net_month * 100:+.2f}% a month beyond the index on "
                  "years never used to choose the strategy, after costs and "
                  "the survivorship haircut"),
        Criterion(f"At least {MIN_PAPER_TRADES} closed paper trades",
                  len(ev.paper_r) >= MIN_PAPER_TRADES,
                  f"{len(ev.paper_r)} so far"),
        Criterion("Paper results reliably above zero",
                  t >= MIN_T_STAT and len(ev.paper_r) >= MIN_PAPER_TRADES,
                  f"t-statistic {t:.2f}, needs {MIN_T_STAT:.1f}"),
        Criterion(f"At least {MIN_PAPER_MONTHS} months, averaging above the index",
                  len(months) >= MIN_PAPER_MONTHS and avg > ev.index_month,
                  f"{len(months)} month(s), averaging {avg * 100:+.2f}%"),
        Criterion(f"Paper drawdown within {MAX_PAPER_DRAWDOWN:.0%}",
                  ev.paper_drawdown <= MAX_PAPER_DRAWDOWN,
                  f"worst fall {ev.paper_drawdown:.1%}"),
        Criterion("Monthly review shows no drift from the playbook",
                  ev.review_drifts == 0,
                  f"{ev.review_drifts} principle(s) drifting"),
    ]


def live_step_up(ev: Evidence) -> list[Criterion]:
    """From PILOT to LIMITED, or LIMITED to FULL."""
    need = MONTHS_AT_STAGE.get(ev.stage, 0)
    months = list(ev.live_months)
    avg = sum(months) / len(months) if months else 0.0
    return [
        Criterion(f"{need} months at {ev.stage}",
                  ev.months_at_stage >= need,
                  f"{ev.months_at_stage} so far"),
        Criterion("Real results match paper",
                  bool(months) and avg >= ev.index_month * 0.8,
                  f"{avg * 100:+.2f}% a month live"),
        Criterion("Real costs close to the model",
                  ev.slippage_ratio is not None
                  and ev.slippage_ratio <= MAX_SLIPPAGE_RATIO,
                  "not measured yet" if ev.slippage_ratio is None
                  else f"{ev.slippage_ratio:.2f}x the modelled cost"),
    ]


def must_demote(ev: Evidence, worst_hist_month: float) -> tuple[bool, str]:
    """The kill switch. Checked before anything else, at every live stage.

    A professional cuts size the moment live results leave the historical
    range — before understanding why, not after.
    """
    if ev.stage == PAPER:
        return False, ""
    months = list(ev.live_months)
    if months and months[-1] < worst_hist_month * 1.5:
        return True, (f"last month {months[-1] * 100:+.2f}% is half again worse "
                      f"than the worst historical month ({worst_hist_month * 100:+.2f}%)")
    if len(months) >= 2 and all(m < -0.0541 for m in months[-2:]):
        return True, "two consecutive months worse than nine historical months in ten"
    if ev.review_drifts:
        return True, f"{ev.review_drifts} playbook principle(s) drifting live"
    return False, ""


@dataclass(frozen=True)
class Verdict:
    stage: str
    next_stage: str | None
    eligible: bool
    criteria: list[Criterion]
    demote: bool = False
    demote_reason: str = ""


def evaluate(ev: Evidence, worst_hist_month: float = -0.12) -> Verdict:
    demote, why = must_demote(ev, worst_hist_month)
    if demote:
        lower = STAGES[max(0, STAGES.index(ev.stage) - 1)]
        return Verdict(lower, ev.stage, False, [], True, why)
    if ev.stage == FULL:
        return Verdict(FULL, None, False, [])
    nxt = STAGES[STAGES.index(ev.stage) + 1]
    criteria = paper_to_pilot(ev) if ev.stage == PAPER else live_step_up(ev)
    return Verdict(ev.stage, nxt, all(c.passed for c in criteria), criteria)


# Can each model ever reach live trading? Measured on fair historical data
# (stocks chosen by liquidity at the time, costs included), with 2009-15 as
# years never used to choose anything.
MODEL_VERDICTS: dict[str, tuple[str, str]] = {
    "stocks": ("CLOSEST",
               "Core-and-satellite: idle capital in the index, dip-buying trades "
               "on top. Dip-buying adds +0.56% a trade beyond the index since "
               "2016 (t 4.0) and +0.44% on 2009-15 (t 2.5); the account beats "
               "the index (+1.21% vs +1.00% a month) after costs and a "
               "survivorship haircut. Unseen years add only +0.06% a month after "
               "that haircut, below the bar. Capitulation (oversold in a volatile "
               "decline, held 20 days) beat the index in all three periods. "
               "Momentum's gains were the market's, so it is never given capital."),
    "contagion": ("NO",
                  "Following the leader lost on 745,570 cases. The rebound looked "
                  "positive (13 of 18 years), but its stocks had betas of 1.2-1.7: "
                  "after removing beta it was -0.14% / +0.11% / +0.11% — the market's "
                  "rebound, not skill. No edge in any tested form. Recorded on "
                  "paper for learning; expected edge set to zero."),
    "crypto15m": ("NO",
                  "No short-term edge either way (breakouts -4.45% over 20 days, "
                  "dips -3.64% over 5, past year). Over the long run Bitcoin grew "
                  "about x110 since 2016 with a -90% fall; the 200-day trend rule "
                  "gave x95 with -80%. New: holding except while STOCKS are in a "
                  "volatile decline gave x155, cutting 2022 from -76% to -28% — "
                  "promising, resting on few bear markets. Advises, never trades."),
    "news": ("NO (AT THIS SPEED)",
             "58,000 earnings reports: the whole reaction happens on the day "
             "(+2.0% for big beats, -3.2% for big misses, beyond the index) and "
             "the following 19 days show no reliable drift. A system reading "
             "news hours later trades after the move. Kept for learning and "
             "context; GDELT now arrives through its bulk files."),
    "opportunity": ("NOT A TRADING MODEL",
                    "One-off situations cannot be backtested as a series. A "
                    "research feed, judged by the intake gate."),
}


def describe_models() -> str:
    lines = ["Can each model reach live trading?", ""]
    for model, (verdict, why) in MODEL_VERDICTS.items():
        lines.append(f"  {model:<12} {verdict}")
        lines.append(f"      {why}")
    return "\n".join(lines)


def describe(v: Verdict) -> str:
    lines = [f"Promotion ladder — current stage: {v.stage}", ""]
    if v.demote:
        lines.append(f"  DEMOTED from {v.next_stage}: {v.demote_reason}")
        return "\n".join(lines)
    if v.next_stage is None:
        lines.append("  At full size. The kill switch is still checked every month.")
        return "\n".join(lines)
    passed = sum(c.passed for c in v.criteria)
    lines.append(f"  To reach {v.next_stage}: {passed} of {len(v.criteria)} criteria met")
    for c in v.criteria:
        lines.append(f"    [{'x' if c.passed else ' '}] {c.name} — {c.detail}")
    lines.append("")
    if v.eligible:
        lines.append(f"  ELIGIBLE for {v.next_stage}. Eligibility is not execution: "
                     "real trading needs an execution layer that does not exist "
                     "yet, and a deliberate human decision to build and enable it.")
    else:
        lines.append("  Not eligible. Each unchecked line is a reason real money "
                     "should not follow these signals yet.")
    return "\n".join(lines)
