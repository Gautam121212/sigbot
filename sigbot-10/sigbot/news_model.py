"""Model A — the news scanner.

Design constraint that shapes everything below: this model has no backtest.
Free news feeds have no point-in-time archive, so there is no honest way to
replay history through it. A model with no out-of-sample evidence is not
allowed to publish a probability.

So it publishes a *score* and an explicit UNVALIDATED flag, logs every call
to the shadow ledger, and only starts attaching an empirical hit rate once
the ledger has resolved enough forward observations to support one. Until
then the message says so, in those words.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Sequence

from .providers.news import EventClassifier, dedupe, jaccard, source_quality, tokens
from .types import Article, Asset, NewsSignal

MIN_OBSERVATIONS_TO_VALIDATE = 100


def match_assets(article: Article, universe: Sequence[Asset]) -> list[tuple[Asset, float]]:
    """Return (asset, relevance) for assets named in the article.

    Relevance is 1.0 for a title hit, 0.5 for a summary-only hit. Anything
    weaker is dropped: an indirect supply-chain inference from a keyword match
    is noise, and pretending otherwise is how a scanner ends up alerting on
    every article that contains the word "apple".
    """
    title_t = tokens(article.title)
    body_t = tokens(article.summary)
    hits: list[tuple[Asset, float]] = []
    for asset in universe:
        terms = asset.match_terms()
        if any(term in title_t for term in terms):
            hits.append((asset, 1.0))
        elif any(term in body_t for term in terms):
            hits.append((asset, 0.5))
    return hits


def time_decay(published_at: datetime, now: datetime, half_life_h: float = 8.0) -> float:
    age_h = max(0.0, (now - published_at).total_seconds() / 3600.0)
    return float(0.5 ** (age_h / half_life_h))


class NewsModel:
    def __init__(
        self,
        universe: Sequence[Asset],
        classifier: EventClassifier,
        score_threshold: float = 0.35,
        half_life_h: float = 8.0,
    ):
        self.universe = list(universe)
        self.classifier = classifier
        self.score_threshold = score_threshold
        self.half_life_h = half_life_h
        self._seen: list[set[str]] = []   # token sets of previously alerted clusters

    def _novelty(self, title: str) -> float:
        t = tokens(title)
        if not self._seen:
            return 1.0
        worst = max(jaccard(t, s) for s in self._seen)
        return float(max(0.0, 1.0 - worst))

    def scan(
        self,
        articles: Sequence[Article],
        now: datetime | None = None,
        stats: dict[str, tuple[int, float, float]] | None = None,
    ) -> list[NewsSignal]:
        """stats maps symbol -> (n_observed, hit_rate, hit_rate_lower) from the
        shadow ledger. Absent or thin stats mean the signal ships unvalidated."""
        now = now or datetime.now(timezone.utc)
        stats = stats or {}
        signals: list[NewsSignal] = []

        for cluster in dedupe(articles):
            lead = cluster[0]
            corroboration = min(1.0, 0.6 + 0.1 * (len(cluster) - 1))
            novelty = self._novelty(lead.title)
            decay = time_decay(lead.published_at, now, self.half_life_h)

            for asset, relevance in match_assets(lead, self.universe):
                impact, rationale = self.classifier.classify(lead, asset.name)
                if impact == 0.0:
                    continue
                quality = source_quality(lead.source)
                score = abs(impact) * relevance * novelty * quality * corroboration * decay
                if score < self.score_threshold:
                    continue

                n_obs, hit, hit_lo = stats.get(asset.symbol, (0, math.nan, math.nan))
                validated = n_obs >= MIN_OBSERVATIONS_TO_VALIDATE

                signals.append(
                    NewsSignal(
                        asset=asset,
                        side="BUY" if impact > 0 else "SELL",
                        raw_score=round(float(impact) * score, 4),
                        magnitude_pct=None,
                        drivers=[
                            rationale,
                            f"relevance {relevance:.1f}",
                            f"novelty {novelty:.2f}",
                            f"source quality {quality:.2f}",
                            f"{len(cluster)} outlet(s) in cluster",
                            f"recency weight {decay:.2f}",
                        ],
                        articles=cluster[:5],
                        validated=validated,
                        hit_rate=None if not validated else hit,
                        hit_rate_lower=None if not validated else hit_lo,
                        n_observed=n_obs,
                    )
                )
                self._seen.append(tokens(lead.title))

        self._seen = self._seen[-500:]
        return signals
