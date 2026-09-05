"""News ingestion.

Honest limitation, stated once and not softened: free RSS feeds carry the
current headline set only. There is no archive, no revision history, and the
publication timestamps are frequently the feed's timestamp rather than the
publisher's. That makes a historical backtest of the news model impossible
with this provider. See `shadow.py` for what is done instead.

To make the news model backtestable you need a point-in-time news archive
(RavenPack, Bloomberg, Refinitiv, Dow Jones). Those cost five figures a year.
That cost is the price of knowing whether the news model works at all.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, Protocol, Sequence

import urllib.request

from ..skips import record_skip

# Ten seconds each. Thirty-nine feeds at worst case is under seven minutes,
# inside the job's timeout — whereas one untimed feed is unbounded.
FEED_TIMEOUT = 10.0
# A feed that streams forever is the same failure as one that hangs.
FEED_MAX_BYTES = 4_000_000
FEED_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
from ..types import Article

# Moved to feeds.py so the list can be categorised and audited. The five that
# used to live here covered no Indian outlet, no listings, no commodities and
# no regulation — while the venture rubric scored gap types that need exactly
# those. See that module for why each source is trusted as far as it is.
from .feeds import (  # noqa: E402
    DEFAULT_FEEDS, DEFAULT_QUALITY, FEED_REGISTRY, SOURCE_QUALITY,
)

__all__ = ["DEFAULT_FEEDS", "FEED_REGISTRY", "SOURCE_QUALITY", "DEFAULT_QUALITY"]

_WORD = re.compile(r"[a-z0-9']+")

STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "for", "and", "or", "as", "at",
    "by", "is", "are", "was", "were", "it", "its", "with", "from", "after",
    "over", "amid", "says", "say", "new", "up", "down",
}


def tokens(text: str) -> set[str]:
    """Content tokens with crude stemming.

    Headline dedupe fails on plural/tense variation ("beats" vs "beat"), so
    strip a trailing 's' on words long enough that it is probably an inflection.
    Not linguistics — just enough to stop one wire story counting three times.
    """
    out = set()
    for w in _WORD.findall(text.lower()):
        if w in STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def source_quality(source: str) -> float:
    """How far to trust an outlet, 0 to 1.

    Matches on the article's own link as well as the feed title, because an
    aggregator republishes other people's work: a Reuters story reaching us via
    Google News is still a Reuters story, and scoring it as "Google News" would
    make every syndicated item look equally unknown.
    """
    s = source.lower()
    for key, val in SOURCE_QUALITY.items():
        if key in s:
            return val
    return DEFAULT_QUALITY


def dedupe(articles: Sequence[Article], threshold: float = 0.55) -> list[list[Article]]:
    """Cluster near-duplicate headlines.

    Ten outlets rewriting one wire story is one piece of information, not ten.
    Returns clusters ordered by earliest publication; the first element of each
    cluster is the earliest-published member, which is the one that mattered.
    """
    clusters: list[list[Article]] = []
    cluster_tokens: list[list[set[str]]] = []
    for art in sorted(articles, key=lambda a: a.published_at):
        t = tokens(art.title)
        placed = False
        for i, members in enumerate(cluster_tokens):
            # Max over members, not the union: unioning inflates the token set
            # and makes every subsequent match harder, so long clusters would
            # stop absorbing the stories that belong to them.
            if max(jaccard(t, m) for m in members) >= threshold:
                clusters[i].append(art)
                members.append(t)
                placed = True
                break
        if not placed:
            clusters.append([art])
            cluster_tokens.append([t])
    return clusters


class RSSProvider:
    def __init__(self, feeds: Iterable[str] | None = None):
        self.feeds = list(feeds or DEFAULT_FEEDS)

    def fetch(self, since: datetime) -> list[Article]:
        try:
            import feedparser
        except ImportError as exc:  # pragma: no cover
            raise ImportError("pip install feedparser") from exc

        now = datetime.now(timezone.utc)
        out: list[Article] = []
        for url in self.feeds:
            try:
                # Fetch with a timeout, then parse the bytes. feedparser.parse
                # accepts a URL and does its own fetching with no timeout at
                # all — one server that accepts a connection and never replies
                # blocks the whole sweep until the task is killed. At 5 feeds
                # that was survivable; at 39 it happens most runs, and it is
                # why `news` and `opportunities` both failed three times in a
                # row while every feed answered fine to a browser.
                request = urllib.request.Request(
                    url, headers={"User-Agent": FEED_AGENT})
                with urllib.request.urlopen(request, timeout=FEED_TIMEOUT) as resp:
                    body = resp.read(FEED_MAX_BYTES)
                parsed = feedparser.parse(body)
            except Exception as exc:  # noqa: BLE001 - one dead feed must not stop the sweep
                record_skip("news_feeds", url, exc)
                continue

            # feedparser does not raise on a 404 or a block page — it returns
            # an object with no entries. Without this check a feed that died
            # months ago keeps contributing nothing and saying nothing, and
            # the shrinking coverage looks like a quiet news cycle.
            if getattr(parsed, "bozo", 0) and not parsed.entries:
                record_skip("news_feeds", url,
                            RuntimeError(f"unreadable: "
                                         f"{getattr(parsed, 'bozo_exception', '?')}"))
                continue
            if not parsed.entries:
                record_skip("news_feeds", url,
                            RuntimeError("responded with no entries — the feed "
                                         "may have moved"))
                continue

            source = parsed.feed.get("title", url)
            for e in parsed.entries:
                pub = e.get("published_parsed") or e.get("updated_parsed")
                if not pub:
                    continue
                if len(pub) < 6:
                    continue
                y, mo, d, hh, mm, ss = (int(v) for v in pub[:6])
                ts = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
                if ts < since:
                    continue
                link = e.get("link", "")
                title = e.get("title", "")
                out.append(
                    Article(
                        # Dedupe key only. Never a security boundary, so the
                        # choice of hash does not matter — but say so, or the
                        # scanner finding stays and teaches you to ignore them.
                        uid=hashlib.sha256(f"{link}|{title}".encode()).hexdigest()[:16],
                        title=title,
                        summary=re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:1200],
                        url=link,
                        # The link, not just the feed name. On an aggregator
                        # the feed title is the aggregator; the link carries
                        # the outlet that actually reported it.
                        source=f"{source} {link}" if "news.google" in url else source,
                        published_at=ts,
                        ingested_at=now,
                    )
                )
        return out


class EventClassifier(Protocol):
    def classify(self, article: Article, asset_name: str) -> tuple[float, str]:
        """Return (signed impact in -1..1, one-line rationale)."""
        ...


BULL = {"beats", "beat", "surge", "surges", "record", "upgrade", "upgraded", "approval",
        "approved", "partnership", "buyback", "raises", "raised", "outperform", "rally",
        "adoption", "inflow", "inflows", "wins", "expansion", "profit", "breakthrough"}
BEAR = {"misses", "miss", "plunge", "plunges", "downgrade", "downgraded", "probe",
        "lawsuit", "recall", "cuts", "cut", "warns", "warning", "layoffs", "fraud",
        "hack", "hacked", "exploit", "outflow", "outflows", "ban", "banned", "delay",
        "delayed", "resigns", "subpoena", "loss", "bankruptcy"}


class LexiconClassifier:
    """Offline fallback. Weak on purpose, and labelled as such downstream.

    A keyword counter cannot read negation, sarcasm, or whether the market had
    already priced the story in. It exists so the pipeline runs without an LLM
    key, not because it is good.
    """

    def classify(self, article: Article, asset_name: str) -> tuple[float, str]:
        t = tokens(f"{article.title} {article.summary}")
        pos, neg = len(t & BULL), len(t & BEAR)
        if pos == neg == 0:
            return 0.0, "no directional keywords matched"
        score = (pos - neg) / max(pos + neg, 1)
        return float(max(-1.0, min(1.0, score))), f"lexicon {pos} bullish / {neg} bearish terms"


class LLMClassifier:
    """Wire this to whatever model you want. Kept behind the same interface so
    swapping it does not touch the scoring or messaging layers."""

    def __init__(self, call_fn):
        self.call_fn = call_fn  # (prompt: str) -> str returning JSON

    def classify(self, article: Article, asset_name: str) -> tuple[float, str]:
        import json

        prompt = (
            "You are scoring a news item for its likely effect on one asset's price "
            "over the next 24 hours. Answer with JSON only, no prose.\n"
            f"Asset: {asset_name}\nHeadline: {article.title}\nSummary: {article.summary}\n"
            'Return {"impact": <float -1..1>, "reason": "<12 words max>", '
            '"already_priced_in": <true|false>}'
        )
        try:
            data = json.loads(self.call_fn(prompt))
            impact = float(data.get("impact", 0.0))
            if data.get("already_priced_in"):
                impact *= 0.3
            return max(-1.0, min(1.0, impact)), str(data.get("reason", ""))[:120]
        except Exception as exc:  # handled: returns a rationale string naming the failure
            return 0.0, f"classifier failed: {type(exc).__name__}"
