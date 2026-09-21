"""What a month should look like — measured on history, not assumed.

HOW THE NUMBERS WERE MADE
-------------------------
Liquid US large caps, January 2016 to now: 129 months. Each strategy's
signals were traded the way sigbot trades them: 1% of capital risked per
trade, a stop at three times the average daily range, ten-day holds, and at
most six positions open — which caps a month at about twelve trades. Each
month took its first twelve signals in the order they fired, so no month was
allowed to cherry-pick its best trades.

Costs were then charged with the same square-root impact model the paper book
uses, at the measured median trade: a 9.7% stop, hence a position of about
10.3% of capital, in a name trading about $107M a day with 3.23% daily
volatility. That comes to roughly 0.20% of the account per month.

WHAT THEY SAY
-------------
Net of costs, running both schools earns about what simply holding the index
earned on average — and more in the typical month, with a noticeably smaller
worst month. Neither school alone keeps up with the index. The case for this
system is therefore not "beat the market by a wide margin". It is "match the
market with shallower falls", and only when both schools run together.

A single month tells you almost nothing: even the best combination lost money
in about four months out of ten.
"""
from __future__ import annotations

from dataclasses import dataclass

# Measured cost of one month's trading, as a fraction of the account.
#   per side  = 0.05% base + 3.23% volatility x sqrt(10.3k / 107M) = 0.082%
#   per trade = 10.3% of capital x 0.164% round trip             = 0.017%
#   per month = 12 trades                                          = 0.20%
MONTHLY_COST = 0.0020


@dataclass(frozen=True)
class Benchmark:
    name: str
    months: int
    avg_month: float        # fractions: 0.0119 = +1.19%
    median_month: float
    bad_month_p10: float    # one month in ten is this bad or worse
    worst_month: float
    months_up: float        # share of months that made money
    trades_per_month: float
    costs_apply: bool = True

    @property
    def net_avg(self) -> float:
        cost = MONTHLY_COST * (self.trades_per_month / 12.0) if self.costs_apply else 0.0
        return self.avg_month - cost

    @property
    def net_median(self) -> float:
        cost = MONTHLY_COST * (self.trades_per_month / 12.0) if self.costs_apply else 0.0
        return self.median_month - cost


BOTH_SCHOOLS = Benchmark("Both schools together", 129, 0.0119, 0.0164,
                         -0.0529, -0.1169, 0.612, 12.0)
MOMENTUM = Benchmark("Momentum alone", 129, 0.0094, 0.0103,
                     -0.0607, -0.1200, 0.566, 12.0)
WASHOUT = Benchmark("Washout alone", 123, 0.0063, 0.0073,
                    -0.0435, -0.1153, 0.593, 10.4)
HOLD_INDEX = Benchmark("Buy and hold the S&P 500", 129, 0.0100, 0.0121,
                       -0.0502, -0.1661, 0.667, 0.0, costs_apply=False)

ALL = (BOTH_SCHOOLS, MOMENTUM, WASHOUT, HOLD_INDEX)

# What sigbot runs now, and so what its live months are held against.
EXPECTED = BOTH_SCHOOLS


def judge_month(live_return: float, bench: Benchmark = EXPECTED) -> tuple[str, str]:
    """One month against history. Returns (verdict, plain explanation).

    Deliberately modest. A losing month happened four times in ten even for
    the best combination, so one bad month is not evidence of anything — only
    a month worse than nine in ten historical ones earns a flag.
    """
    if live_return <= bench.bad_month_p10:
        return ("BELOW RANGE",
                f"{live_return * 100:+.2f}% is worse than nine historical months "
                f"in ten ({bench.bad_month_p10 * 100:+.2f}). Worth a look — "
                "but check whether the whole market fell before blaming the "
                "system.")
    if live_return < 0:
        return ("NORMAL LOSS",
                f"{live_return * 100:+.2f}%. About four months in ten lose money "
                "even in the best historical combination; this is inside that.")
    if live_return >= bench.net_median:
        return ("ABOVE TYPICAL",
                f"{live_return * 100:+.2f}%, above the typical month net of costs "
                f"({bench.net_median * 100:+.2f}%). One good month is not a trend.")
    return ("NORMAL GAIN",
            f"{live_return * 100:+.2f}%, a gain but below the typical month net "
            f"of costs ({bench.net_median * 100:+.2f}%).")


def judge_run(live_months: list[float], bench: Benchmark = EXPECTED) -> tuple[str, str]:
    """Several months together, against the expected average."""
    n = len(live_months)
    if n < 6:
        return ("TOO EARLY", f"{n} month(s). The average of fewer than six "
                             "months is mostly luck.")
    avg = sum(live_months) / n
    if avg < HOLD_INDEX.avg_month - 0.005:
        return ("BEHIND THE INDEX",
                f"{avg * 100:+.2f}% a month over {n} months, against "
                f"{HOLD_INDEX.avg_month * 100:+.2f}% for simply holding the index. "
                "If this persists, holding the index would have been better.")
    return ("ON TRACK", f"{avg * 100:+.2f}% a month over {n} months, against an "
                        f"expected {bench.net_avg * 100:+.2f}% net of costs.")


def table() -> str:
    lines = ["Monthly benchmarks, 2016 to now (net = after estimated costs)", "",
             f"  {'':<28}{'avg':>8}{'net avg':>9}{'median':>8}{'1-in-10':>9}"
             f"{'worst':>9}{'up':>6}"]
    for b in ALL:
        lines.append(f"  {b.name:<28}{b.avg_month * 100:>+7.2f}%{b.net_avg * 100:>+8.2f}%"
                     f"{b.median_month * 100:>+7.2f}%{b.bad_month_p10 * 100:>+8.2f}%"
                     f"{b.worst_month * 100:>+8.2f}%{b.months_up * 100:>5.0f}%")
    return "\n".join(lines)
