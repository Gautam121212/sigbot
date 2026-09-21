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
Measured fairly, and after costs, running both schools earned about +0.54% a
month from 2016 against +1.00% for simply holding the index — and roughly
nothing in 2009-2015, a period the strategies never saw, while the index rose
strongly. Neither school alone did better.

The honest conclusion is that on history this system has TRAILED the index,
not matched it. Its one consistent advantage is a smaller worst month. That is
worth knowing before any money follows it.

A single month tells you almost nothing: even the combination lost money in
about four months out of ten.
"""
from __future__ import annotations

from dataclasses import dataclass

# Measured cost of one month's trading, as a fraction of the account.
#   per side  = 0.05% base + 3.23% volatility x sqrt(10.3k / 107M) = 0.082%
#   per trade = 10.3% of capital x 0.164% round trip             = 0.017%
#   per month = 12 trades                                          = 0.20%
# A FLOOR, not an estimate: measured on large caps, while the fair universe
# includes thinner names that cost more to trade.
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


# FAIR measurement: stocks chosen by liquidity AT THE TIME of each trade
# (over 500k shares and $20M traded a day), all US common stocks.
#
# The first version chose stocks by their size TODAY, which uses information
# nobody had when the trade was made: it keeps companies that grew into large
# caps and drops those that faded. It inflated every figure, and the washout
# school most of all (+0.63% a month became +0.11%) because a crashed stock
# that stayed down is exactly what that filter removed. Those numbers were
# wrong and are gone.
#
# Even these are flattered: the database drops companies that later went bust
# entirely (SVB, Bed Bath & Beyond, First Republic, WeWork are absent), so no
# filter can include them. Read every figure below as an upper bound.
BOTH_SCHOOLS = Benchmark("Both schools together", 129, 0.0074, 0.0119,
                         -0.0541, -0.1200, 0.620, 12.0)
MOMENTUM = Benchmark("Momentum alone", 129, 0.0073, 0.0141,
                     -0.0618, -0.1200, 0.581, 12.0)
WASHOUT = Benchmark("Washout alone", 122, 0.0011, 0.0052,
                    -0.0399, -0.1200, 0.549, 10.5)
HOLD_INDEX = Benchmark("Buy and hold the S&P 500", 129, 0.0100, 0.0121,
                       -0.0502, -0.1661, 0.667, 0.0, costs_apply=False)

# OUT OF SAMPLE: 2009-2015, a period neither school was chosen on. The only
# test here of whether the choice itself was overfitted — and it was not
# reassuring: the combination earned roughly nothing after costs, while the
# index rose strongly.
OUT_OF_SAMPLE = Benchmark("Both schools, 2009-15 (unseen)", 84, 0.0020, 0.0038,
                          -0.0571, -0.0969, 0.524, 11.7)

ALL = (BOTH_SCHOOLS, MOMENTUM, WASHOUT, OUT_OF_SAMPLE, HOLD_INDEX)

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


# ---------------------------------------------------------------------------
# CORE-AND-SATELLITE — the structure sigbot now uses for stocks.
#
# Idle capital is held in the index (the core); strategy trades are the
# satellite. A trade is therefore judged by what it earns BEYOND the index
# over the same days on the same money — the test professional allocators
# apply. Measured on fair data (liquid at the time, $20M+ a day):
#
#   excess per trade        2016+            2009-15 (unseen)
#   dip-buying, 10 days     +0.559% (t 4.0)  +0.435% (t 2.5)
#   momentum, 60 days       -0.046% (t -0.2) -0.834% (t -5.8)
#
# Momentum's gains were the market's, so under this structure it duplicates
# the core and is never given capital. Dip-buying adds return in both periods.
#
# SURVIVORSHIP HAIRCUT. The database omits companies that later went bust,
# and dip-buying is the strategy most flattered by that: it buys stocks after
# they fall. A missing bankrupt stock would almost certainly have hit its
# stop, so if even a few percent of these trades are missing the edge shrinks
# by roughly 0.2% a trade. The ladder uses the edge AFTER that haircut.
SURVIVORSHIP_HAIRCUT = 0.002

POSITION_OF_CAPITAL = 0.103     # 1% risk / ~9.7% median stop
COST_PER_TRADE = 0.00017        # of capital, from the square-root cost model


@dataclass(frozen=True)
class Satellite:
    name: str
    excess_per_trade: float     # beyond the index, same days, before costs
    t_stat: float
    trades_per_month: float

    def monthly_alpha(self, haircut: float = SURVIVORSHIP_HAIRCUT) -> float:
        """What the satellite adds to the whole account each month, net."""
        edge = self.excess_per_trade - haircut
        return (self.trades_per_month * POSITION_OF_CAPITAL * edge
                - self.trades_per_month * COST_PER_TRADE)


SATELLITE_IN = Satellite("Dip-buying satellite, 2016+", 0.00559, 4.0, 10.5)
SATELLITE_OOS = Satellite("Dip-buying satellite, 2009-15 (unseen)", 0.00435, 2.5, 9.0)

# The account: the index plus what the satellite adds, after costs and the
# survivorship haircut.
ACCOUNT_NET_MONTH = HOLD_INDEX.avg_month + SATELLITE_IN.monthly_alpha()


# ---------------------------------------------------------------------------
# CRYPTO — Bitcoin through GBTC, the longest history reachable (2016 to now,
# 128 months). GBTC traded at times well above and below the value of its
# Bitcoin, so it is a close but imperfect stand-in.
CRYPTO_HOLD = {"avg_month": 0.075, "median_month": 0.0306, "worst_month": -0.413,
               "growth_x": 109.9, "max_drawdown": -0.899}
CRYPTO_TREND_200 = {"avg_month": 0.0654, "median_month": 0.0, "worst_month": -0.414,
                    "growth_x": 95.3, "max_drawdown": -0.801}
# Short-horizon direction, the past year on eight major coins: breakouts to
# 20-day highs -4.45% over 20 days (28% won); 15%+ weekly drops -3.64% over
# 5 days (34% won). No short-term edge in either direction.


# ---------------------------------------------------------------------------
# NEWS — 58,000 earnings reports on liquid US stocks, 2009 to now, measured
# against the index. The reaction is immediate; there is no reliable drift.
NEWS_EARNINGS = {
    # surprise: (reaction day 2016+, 2009-15, next 19 days 2016+, 2009-15)
    "big beat": (0.0201, 0.0202, -0.0019, -0.0003),
    "in line": (-0.0118, -0.0088, -0.0020, -0.0003),
    "big miss": (-0.0324, -0.0294, 0.0100, -0.0065),
}
