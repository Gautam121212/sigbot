"""The screen — how the 100 get chosen, from data rather than opinion.

## What this fixes

The previous version filled the board structurally: interleave by asset class,
take the first hundred. You correctly pushed back. The system already knows how
to analyse an asset — historical bars, news reactivity, links to the big names
that move it — so the board should come out of that analysis, not out of an
ordering.

## The distinction that keeps it honest

A high screen score does **not** predict profit. It says this asset has
properties that make it worth spending checks on. That is a resource-allocation
decision, and it is a different claim entirely.

The difference matters because you only get so many checks. Every asset on the
board consumes attention and takes months to accumulate a record. Spending those
checks on something that barely moves, barely trades, or has no relationship to
anything the system watches is waste — and you would not find that out for a
year. The screen removes the assets that could not produce a usable answer even
if the underlying idea were sound.

## What is measured

Every input is computable from history today. None is a forecast.

  liquidity     does it trade enough to get in and out of, with no long gaps
  movability    do typical daily moves clear trading costs at all
  stability     does it behave the same in the first half of history as the
                second, or has it changed into a different asset
  reactivity    does it move more on event days than on ordinary ones — an
                asset that ignores news is not worth a news model
  linkage       does it follow any of the anchors with a next-day lag that
                survives multiple-testing correction

`stability` carries real weight because an asset whose behaviour changed
halfway through is one where the historical record will not describe the future
— which makes every check spent on it worth less.

## Replacement

Rotation replaces one or two at a time, never a batch, and a replacement enters
through this same screen. The board is not rebuilt; it is repaired.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .contagion import build_network
from .recurrence import news_sensitivity, volume_event_days
from .skips import record_skip, report, skipped_count
from .stats import wilson_interval

# criterion -> (starting weight, what it asks)
CRITERIA: dict[str, tuple[float, str]] = {
    "liquidity": (16.0, "Does it trade enough to get in and out of, without gaps?"),
    "movability": (16.0, "Do typical daily moves clear trading costs at all?"),
    "stability": (18.0, "Does it behave the same across both halves of its history?"),
    "reactivity": (13.0, "Does it move more on event days than ordinary ones?"),
    "linkage": (12.0, "Does it follow any anchor with a next-day lag?"),
    "backtested": (13.0, "Does a walk-forward model find any skill on it out-of-sample?"),
    "track_record": (12.0, "Once it has a live record, is that record any good?"),
}

# Nothing below this many resolved checks may influence selection. A screen that
# reweights on thin records is the same overfitting the rest of this project
# spends its time preventing, just moved one layer up.
MIN_RECORD_FOR_FEEDBACK = 60
MIN_ASSETS_FOR_LEARNING = 25
MAX_WEIGHT_STEP = 2.0

MIN_BARS = 400
COST_FLOOR = 0.004      # a day that moves less than this cannot pay for itself


@dataclass
class ScreenResult:
    symbol: str
    kind: str
    scores: dict[str, float] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    usable: bool = True
    reject_reason: str = ""
    weights: dict[str, float] | None = None

    @property
    def total(self) -> float:
        if not self.usable:
            return 0.0
        w = self.weights or {k: v for k, (v, _) in CRITERIA.items()}
        return round(sum(self.scores.get(k, 0.0) / 10.0 * w.get(k, 0.0)
                         for k in CRITERIA), 1)

    @property
    def weakest(self) -> str:
        if not self.scores:
            return "no data"
        k = min(self.scores, key=lambda x: self.scores[x])
        return f"{k} ({self.scores[k]:.1f}/10)"

    def render(self) -> str:
        if not self.usable:
            return f"{self.symbol}: rejected — {self.reject_reason}"
        parts = ", ".join(f"{k} {self.scores.get(k, 0):.0f}" for k in CRITERIA)
        return f"{self.symbol}: {self.total:.0f}/100 ({parts})"


def _clip10(x: float) -> float:
    return float(np.clip(x, 0.0, 10.0))


def score_asset(bars: pd.DataFrame, symbol: str, kind: str,
                linkage_beta: float = 0.0, oof_skill: float | None = None,
                record: tuple[int, float] | None = None) -> ScreenResult:
    """Score one asset on properties measurable from its own history."""
    res = ScreenResult(symbol=symbol, kind=kind)
    if bars is None or len(bars) < MIN_BARS:
        res.usable = False
        res.reject_reason = (f"only {0 if bars is None else len(bars)} bars of history; "
                             f"{MIN_BARS} needed before anything can be measured")
        return res

    close = bars["close"].astype(float)
    r = np.log(close).diff().dropna()
    if r.empty or not np.isfinite(r).all():
        res.usable = False
        res.reject_reason = "price history has gaps or bad values"
        return res
    if r.std() == 0 or float((r != 0).mean()) < 0.5:
        # A price that barely changes is a data problem, not a low score. Left
        # scoreable it would sit at the bottom of the board consuming a slot.
        res.usable = False
        res.reject_reason = ("price barely moves — either it is untradeable or the "
                             "feed is stale")
        return res

    # Liquidity: traded value, and how much of the period actually has data.
    value = (close * bars["volume"].astype(float)).median()
    coverage = len(bars) / max((bars.index[-1] - bars.index[0]).days / 1.45, 1)
    liq = _clip10(np.log10(max(value, 1.0)) - 4.0) * min(coverage, 1.0)
    res.scores["liquidity"] = liq
    res.notes["liquidity"] = f"median traded value {value:,.0f}, coverage {coverage:.0%}"

    # Movability: the share of days that move enough to pay for a round trip.
    payable = float((r.abs() > COST_FLOOR).mean())
    res.scores["movability"] = _clip10(payable * 14.0)
    res.notes["movability"] = f"{payable:.0%} of days move more than {COST_FLOOR:.1%}"

    # Stability: same asset in both halves, or two different ones stitched together.
    half = len(r) // 2
    v1, v2 = r.iloc[:half].std(), r.iloc[half:].std()
    if v1 > 0 and v2 > 0:
        ratio = float(min(v1, v2) / max(v1, v2))
        res.scores["stability"] = _clip10(ratio * 10.0)
        res.notes["stability"] = (f"volatility {v1:.2%} then {v2:.2%} — "
                                  f"{'consistent' if ratio > 0.6 else 'changed materially'}")
    else:
        res.scores["stability"] = 0.0
        res.notes["stability"] = "no variation in one half of the history"

    # Reactivity: does it care about event days at all?
    try:
        ev = volume_event_days(bars)
        sens = news_sensitivity(r, ev.reindex(r.index, fill_value=False), symbol)
        amp = sens.amplification if sens else 1.0
    except Exception as exc:  # noqa: BLE001
        # A failed reactivity measurement scored the asset as exactly neutral,
        # which is indistinguishable from a measured neutral result.
        record_skip("reactivity", symbol, exc)
        amp = 1.0
    res.scores["reactivity"] = _clip10((amp - 1.0) * 12.0)
    res.notes["reactivity"] = f"moves {amp:.2f}x more on event days"

    # Linkage: strongest next-day response to an anchor that survived correction.
    res.scores["linkage"] = _clip10(abs(linkage_beta) * 40.0)
    res.notes["linkage"] = (f"next-day beta {linkage_beta:+.3f} to its strongest anchor"
                            if linkage_beta else "no surviving link to any anchor")

    # Backtested skill: a walk-forward model, refit repeatedly on past windows and
    # scored on data it never saw. This is the "run the assumptions over and over"
    # part, and it is the only screen input that has been tested out-of-sample.
    if oof_skill is None:
        res.scores["backtested"] = 5.0
        res.notes["backtested"] = "not backtested yet — held neutral, not assumed good"
    else:
        res.scores["backtested"] = _clip10(5.0 + oof_skill * 400.0)
        res.notes["backtested"] = (
            f"out-of-sample skill {oof_skill:+.4f} — "
            f"{'beats' if oof_skill > 0 else 'loses to'} guessing the base rate")

    # Live record: what actually happened after the system called it.
    if not record or record[0] < MIN_RECORD_FOR_FEEDBACK:
        n = record[0] if record else 0
        res.scores["track_record"] = 5.0
        res.notes["track_record"] = (
            f"only {n} live checks — below {MIN_RECORD_FOR_FEEDBACK}, so it is held "
            "neutral rather than counted either way")
    else:
        n, hits = record
        lower, _ = wilson_interval(hits, n, 0.90)
        res.scores["track_record"] = _clip10((lower - 0.40) * 40.0)
        res.notes["track_record"] = (
            f"{n} live checks, right {hits / n:.0%}, worst case {lower:.0%}")
    return res


def linkage_betas(returns: dict[str, pd.Series], anchors: list[str],
                  candidates: list[str], alpha: float = 0.10) -> dict[str, float]:
    """Strongest FDR-surviving next-day beta per candidate. Zero if none survive.

    The correction matters here: without it, screening a hundred-odd candidates
    against a dozen anchors hands roughly 5% of pairs a spurious link, and the
    board fills with assets selected on noise.
    """
    out: dict[str, float] = {}
    try:
        for link in build_network(returns, anchors, candidates, alpha=alpha):
            if link.tradeable:
                prev = out.get(link.dependent, 0.0)
                if abs(link.beta_lagged) > abs(prev):
                    out[link.dependent] = link.beta_lagged
    except Exception as exc:  # noqa: BLE001
        record_skip("linkage", "network", exc)
    return out


def backtest_skill(bars: pd.DataFrame, train_window: int = 750) -> float | None:
    """Out-of-fold Brier skill from a walk-forward fit. None if it cannot be run.

    This is the expensive input and the only one tested on data the model never
    saw. Everything else describes the asset; this one describes whether the
    asset can be predicted.
    """
    try:
        from .backtest import walk_forward
        from .features import build_dataset

        res = walk_forward(build_dataset(bars), train_window=train_window, step=42)
        if res.n_predictions < 200:
            return None
        return float(res.brier_baseline - res.brier)
    except Exception:  # handled: counted by report('screen') and printed by explain
        return None


def screen(bars_by_symbol: dict[str, pd.DataFrame], kinds: dict[str, str],
           anchors: list[str] | None = None, alpha: float = 0.10,
           records: dict[str, tuple[int, float]] | None = None,
           run_backtests: bool = False,
           weights: dict[str, float] | None = None) -> list[ScreenResult]:
    """Score every candidate. Returns all of them, best first, rejects last.

    `run_backtests` is off by default because a walk-forward fit per asset takes
    seconds, and 156 of them takes minutes. Turn it on for the periodic full
    screen; leave it off for a quick re-rank.
    """
    returns = {}
    for sym, bars in bars_by_symbol.items():
        try:
            returns[sym] = np.log(bars["close"].astype(float)).diff().dropna()
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the screen
            record_skip("screen", sym, exc)

    betas: dict[str, float] = {}
    if anchors:
        live = [a for a in anchors if a in returns]
        cands = [c for c in returns if c not in live]
        if live and cands:
            betas = linkage_betas(returns, live, cands, alpha)

    records = records or {}
    results = []
    for sym, bars in bars_by_symbol.items():
        try:
            skill = backtest_skill(bars) if run_backtests else None
            r = score_asset(bars, sym, kinds.get(sym, "equity"), betas.get(sym, 0.0),
                            skill, records.get(sym))
        except Exception as exc:  # noqa: BLE001
            record_skip("screen", sym, exc)
            continue
        r.weights = dict(weights) if weights else None
        results.append(r)
    return sorted(results, key=lambda x: (not x.usable, -x.total, x.symbol))


def learn_weights(results: list[ScreenResult], records: dict[str, tuple[int, float]],
                  current: dict[str, float] | None = None) -> tuple[dict[str, float], str]:
    """Reweight the criteria by which ones actually predicted a good record.

    This is the part that learns from mistakes. For every asset with a thick
    enough live record, correlate each criterion's score against the realised
    hit rate. A criterion that predicted nothing loses weight; one that
    predicted well gains it.

    Three guards, because reweighting is where this could quietly go wrong:

      * nothing counts below MIN_RECORD_FOR_FEEDBACK checks per asset
      * nothing moves at all below MIN_ASSETS_FOR_LEARNING assets — with five
        assets, correlations are noise wearing a number
      * no weight moves more than MAX_WEIGHT_STEP per cycle, so a single odd
        quarter cannot rewrite the screen

    Returns the new weights and a sentence explaining what changed.
    """
    base = dict(current or {k: w for k, (w, _) in CRITERIA.items()})
    usable = [r for r in results
              if r.usable and records.get(r.symbol, (0, 0))[0] >= MIN_RECORD_FOR_FEEDBACK]
    if len(usable) < MIN_ASSETS_FOR_LEARNING:
        return base, (f"Weights unchanged: {len(usable)} assets have a record thick "
                      f"enough to learn from, and {MIN_ASSETS_FOR_LEARNING} are needed. "
                      "Correlations on fewer than that are noise wearing a number.")

    rates = np.array([records[r.symbol][1] / records[r.symbol][0] for r in usable])
    moved: list[str] = []
    for crit in CRITERIA:
        col = np.array([r.scores.get(crit, 5.0) for r in usable])
        if col.std() == 0 or rates.std() == 0:
            continue
        corr = float(np.corrcoef(col, rates)[0, 1])
        step = float(np.clip(corr * MAX_WEIGHT_STEP * 2, -MAX_WEIGHT_STEP, MAX_WEIGHT_STEP))
        new = max(2.0, base[crit] + step)
        if abs(new - base[crit]) > 0.05:
            moved.append(f"{crit} {base[crit]:.0f}->{new:.0f} (corr {corr:+.2f})")
        base[crit] = new

    total = sum(base.values())
    base = {k: round(v * 100.0 / total, 1) for k, v in base.items()}
    note = (f"Reweighted from {len(usable)} assets with live records. "
            + ("; ".join(moved) if moved else "no criterion moved materially."))
    return base, note


def select(results: list[ScreenResult], target: int = 100,
           max_share: float = 0.55) -> list[ScreenResult]:
    """Take the best `target`, with no single asset class over `max_share`.

    The cap is not diversification for its own sake. Crypto has more bars per
    week than shares, so it scores better on movability and would crowd out the
    equity side entirely — and a board of one asset class cannot tell you
    whether an edge is real or a property of that class.
    """
    usable = [r for r in results if r.usable]
    cap = int(target * max_share)
    picked: list[ScreenResult] = []
    counts: dict[str, int] = {}

    for r in usable:
        if len(picked) >= target:
            break
        if counts.get(r.kind, 0) >= cap:
            continue
        picked.append(r)
        counts[r.kind] = counts.get(r.kind, 0) + 1

    # The cap is hard. An earlier version backfilled the shortfall with overflow
    # from the capped class, which quietly defeated the cap and contradicted the
    # reason for having one. A board that is short is better than a board that
    # is all one asset class: the second cannot tell you whether an edge is real
    # or a property of the class.
    return picked


def explain(results: list[ScreenResult], target: int = 100,
            attempted: int | None = None) -> str:
    usable = [r for r in results if r.usable]
    rejected = [r for r in results if not r.usable]
    picked = select(results, target)
    short = ("" if len(picked) >= target else
             f" Short of {target} because the asset-class cap binds — better a "
             "short board than one made of a single class.")
    attempted = attempted if attempted is not None else len(results) + skipped_count("screen")
    skipped = report("screen", attempted)
    lines = [
        f"Screened {len(results)} candidates: {len(usable)} usable, "
        f"{len(rejected)} rejected outright.",
        f"Selected {len(picked)}.{short}",
        *([skipped.line()] if skipped.skipped else []),
        "",
        "A screen score is not a forecast of profit. It says the asset has "
        "properties that make it worth spending checks on — it trades, it moves "
        "enough to cover costs, it has behaved consistently, and it reacts to "
        "something. Assets failing that cannot give a usable answer even if the "
        "underlying idea is sound, and you would not find out for a year.",
    ]
    if picked:
        lines += ["", "Strongest:"] + [f"  {r.render()}" for r in picked[:5]]
        lines += ["", "Weakest still selected:"] + [f"  {r.render()}" for r in picked[-3:]]
    if rejected:
        lines += ["", f"Rejected ({len(rejected)}):"] + \
                 [f"  {r.render()}" for r in rejected[:5]]
    return "\n".join(lines)
