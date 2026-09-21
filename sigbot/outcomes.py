"""Year by year: how each model's old strategy and its new one would have done.

Averages over a period hide what a yearly list shows. The follow-on rebound
averages +0.37% a year beyond the index — and lost four years running,
2022-2025. That is the kind of learning gap only a year-by-year record finds.
All figures are beyond the index (stocks, follow-on) or total return (crypto),
on fair data: liquid at the time, $20M+ traded a day.
"""
from __future__ import annotations

YEARS = tuple(range(2009, 2027))

# Stocks, excess per trade. Old: RSI<20 washout, 10 days. New: regime-switching
# satellite — capitulation in volatile declines, momentum in calm uptrends, 20 days.
STOCKS_OLD = (7.49, 0.19, -0.76, 0.97, 1.24, 0.54, 0.49, -0.57, 0.81, 1.27,
              -0.01, -1.45, 0.11, 0.93, -1.07, -0.65, 1.17, 2.51)
STOCKS_NEW = (2.59, 1.19, 1.33, 0.77, 0.37, 1.20, -1.64, 1.04, -0.30, 1.47,
              2.33, 0.24, 0.32, 0.94, -0.33, 1.48, -0.76, 0.76)

# Follow-on, excess per trade. Old: follow the leader, next day. New: buy the
# sympathy rebound after a leader falls 4%+, 5 days.
FOLLOW_OLD = (-0.22, 0.11, -0.04, 0.00, 0.04, 0.10, -0.02, 0.35, -0.05, -0.04,
              0.06, -0.01, -0.27, -0.03, 0.20, -0.07, -0.10, -0.10)
FOLLOW_NEW = (0.93, 0.28, 0.65, 0.16, 0.74, 0.37, 0.52, -0.32, 0.50, 0.95,
              0.49, 0.17, 0.88, -0.33, -0.72, -0.19, -0.17, 1.73)

# Crypto (Bitcoin via GBTC), total return per year, 2016-2026.
CRYPTO_YEARS = tuple(range(2016, 2027))
CRYPTO_HOLD = (134.0, 1557.2, -82.1, 106.6, 290.7, 7.0, -75.8, 317.6, 113.8, -7.6, -8.1)
CRYPTO_AVOID_PANIC = (125.0, 1557.2, -76.0, 117.6, 315.6, 7.0, -28.0, 82.3, 113.8, -29.6, -9.5)
CRYPTO_RISK_ON_ONLY = (155.4, 1557.2, -77.5, 6.6, 68.4, -10.9, 0.0, 86.7, 64.7, -18.4, -33.4)


def years_positive(series) -> int:
    return sum(1 for x in series if x > 0)


def growth(series_pct) -> float:
    g = 1.0
    for r in series_pct:
        g *= 1 + r / 100
    return g


def mean(series, skip_first: bool = False) -> float:
    s = series[1:] if skip_first else series
    return sum(s) / len(s)


def trailing_decay(series, years: int = 4) -> bool:
    """Every one of the last `years` complete years negative — a fading edge."""
    recent = series[-(years + 1):-1]      # the last year is still in progress
    return len(recent) == years and all(x < 0 for x in recent)


def describe() -> str:
    lines = ["Year by year — old strategy against new", ""]
    lines.append(f"  Stocks:    old {years_positive(STOCKS_OLD)}/18 years positive, "
                 f"{mean(STOCKS_OLD, True):+.2f}% a trade excl. 2009 | new "
                 f"{years_positive(STOCKS_NEW)}/18, {mean(STOCKS_NEW, True):+.2f}%")
    lines.append(f"  Follow-on: old {years_positive(FOLLOW_OLD)}/18 years positive, "
                 f"{mean(FOLLOW_OLD):+.2f}% | new {years_positive(FOLLOW_NEW)}/18, "
                 f"{mean(FOLLOW_NEW):+.2f}%"
                 + ("  — DECAY: negative 2022-2025" if trailing_decay(FOLLOW_NEW) else "")
                 + "; after removing beta: no edge")
    lines.append(f"  Crypto:    hold x{growth(CRYPTO_HOLD):.0f} | avoid stock panics "
                 f"x{growth(CRYPTO_AVOID_PANIC):.0f} | risk-on only "
                 f"x{growth(CRYPTO_RISK_ON_ONLY):.0f}")
    lines.append("  News:      priced on the day across 58,000 earnings reports; no "
                 "yearly strategy to compare yet.")
    lines.append("  Ideas and opportunities: one-off situations — no yearly history exists.")
    return "\n".join(lines)
