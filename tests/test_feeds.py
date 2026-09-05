"""Tests for the feed registry.

Whether a feed is alive today is not something a test settles — that is
`scripts/check_feeds.py`, run from the machine that will do the fetching.
These check the things that are decidable here: that the registry covers the
categories the rubric scores, that trust is not uniform, and that a feed which
goes quiet is recorded rather than silently dropping out.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from sigbot.providers.feeds import (
    DEFAULT_FEEDS, DEFAULT_QUALITY, FEED_REGISTRY, SOURCE_QUALITY, categories,
    describe,
)


def test_every_gap_type_the_rubric_scores_has_a_source():
    """'supply chain shift' was a scored category with no trade feed behind it.
    A model scoring something it cannot observe will never raise it, which
    reads as 'nothing happened' rather than 'nobody was looking'."""
    groups = categories()
    for needed in ("india", "listings", "commodities", "property",
                   "regulation", "supply_chain", "energy"):
        assert groups.get(needed), f"no feed covers {needed}"


def test_the_board_has_indian_coverage():
    """The board holds NSE assets. The original five feeds read no Indian
    outlet at all."""
    assert len(categories()["india"]) >= 5


def test_crypto_no_longer_dominates():
    """Two of the original five feeds were crypto, which is why the first scan
    surfaced a crypto week-ahead piece."""
    share = len(categories()["crypto"]) / len(FEED_REGISTRY)
    assert share < 0.15, f"crypto is {share:.0%} of the feeds"


def test_feeds_are_unique_and_well_formed():
    urls = [u for u, _c, _n in FEED_REGISTRY]
    assert len(urls) == len(set(urls)), "a duplicate feed double-counts a story"
    assert all(u.startswith("https://") for u in urls)
    assert DEFAULT_FEEDS == urls


def test_trust_is_not_uniform():
    """Scoring a wire service and a press-release aggregator alike is how a
    promotional listing note becomes a 'market thesis'."""
    assert SOURCE_QUALITY["reuters"] > SOURCE_QUALITY["moneycontrol"]
    assert SOURCE_QUALITY["moneycontrol"] > SOURCE_QUALITY["cointelegraph"]
    assert SOURCE_QUALITY["federalregister"] >= 0.9, "a regulator is primary"
    assert DEFAULT_QUALITY < 0.5, (
        "an unknown outlet must sit below the venture scanner's floor, or a "
        "random blog clears it at exactly the threshold")


# Scored without a feed of their own. Their stories reach the model as links
# inside other outlets' articles and inside the Google News topic searches, and
# a link to a wire should not be scored as an unknown source. None publishes a
# free feed this machine can read: the last two blocked their own.
CITED_ONLY = {"bloomberg", "ft", "wsj", "spglobal", "agriculture"}


def test_every_scored_source_is_either_a_feed_or_a_known_citation():
    """A quality entry for an outlet that neither publishes here nor gets cited
    is a claim about nothing."""
    def flat(text: str) -> str:
        return text.lower().replace("-", "").replace(".", "")

    joined = flat(" ".join(u for u, _c, _n in FEED_REGISTRY))
    for name in SOURCE_QUALITY:
        if name in CITED_ONLY:
            continue
        assert flat(name) in joined, f"{name} is scored but no feed comes from it"


def test_describe_admits_it_has_not_verified_anything():
    text = describe()
    assert "not a category with coverage" in text
    assert "check_feeds" in text


# ------------------------------------------------- a feed that goes quiet

def _fake_feedparser(monkeypatch, behaviour):
    """Stub the parser AND the fetch. The provider now fetches bytes itself,
    so a test that stubs only the parser reaches the real network — which is
    slow, flaky, and tests the internet rather than the code."""
    import urllib.request

    class _Resp:
        def read(self, _n=None):
            return b"<rss></rss>"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout=None: _Resp())

    module = types.ModuleType("feedparser")

    class Parsed:
        def __init__(self, entries, bozo=0):
            self.entries = entries
            self.bozo = bozo
            self.feed: dict = {}
            self.bozo_exception = "404 Not Found"

    module.parse = lambda body: Parsed(*behaviour("stub"))
    monkeypatch.setitem(sys.modules, "feedparser", module)


def test_an_unreadable_feed_is_recorded(monkeypatch):
    """feedparser does not raise on a 404 — it returns an object with no
    entries. Without a check, a feed that died months ago keeps contributing
    nothing and saying nothing, and shrinking coverage looks like a quiet
    news cycle."""
    from sigbot import skips
    from sigbot.providers.news import RSSProvider

    skips.reset()
    _fake_feedparser(monkeypatch, lambda url: ([], 1))
    RSSProvider(feeds=["https://dead.example/rss"]).fetch(
        datetime.now(timezone.utc) - timedelta(hours=24))

    report = skips.report("news_feeds", 0)
    assert report.skipped == 1
    assert "unreadable" in str(report)


def test_a_feed_with_no_entries_is_recorded(monkeypatch):
    from sigbot import skips
    from sigbot.providers.news import RSSProvider

    skips.reset()
    _fake_feedparser(monkeypatch, lambda url: ([], 0))
    RSSProvider(feeds=["https://moved.example/rss"]).fetch(
        datetime.now(timezone.utc) - timedelta(hours=24))

    report = skips.report("news_feeds", 0)
    assert report.skipped == 1
    assert "may have moved" in str(report)


def test_one_dead_feed_does_not_stop_the_sweep(monkeypatch):
    from sigbot import skips
    from sigbot.providers.news import RSSProvider

    skips.reset()
    _fake_feedparser(monkeypatch,
                     lambda url: ([], 1) if "dead" in url else ([], 0))
    provider = RSSProvider(feeds=["https://dead.example/rss",
                                  "https://alive.example/rss"])
    provider.fetch(datetime.now(timezone.utc) - timedelta(hours=24))
    assert skips.report("news_feeds", 0).skipped == 2


def test_the_validator_rejects_a_200_that_is_not_a_feed():
    """Stooq answers HTTP 200 with an HTML block page. At the HTTP level that
    is indistinguishable from success."""
    import scripts.check_feeds as cf

    src = cf.__doc__ or ""
    assert "not verified" in src
    import inspect
    body = inspect.getsource(cf.check)
    assert '"<html" in lowered' in body
    assert "HTML, not a feed" in body


@pytest.mark.parametrize("category", ["india", "listings", "commodities"])
def test_each_new_category_has_more_than_one_source(category):
    """One feed for a category is a single point of failure dressed as
    coverage."""
    assert len(categories()[category]) >= 2


# --------------------------------------- what your live check revealed

def test_dead_feeds_were_replaced_not_left_in():
    """Reuters retired its public RSS, Moneycontrol answers 403 to anything
    that is not a browser, Agriculture.com moved, S&P blocks non-browsers.
    A feed left in the list after it dies is not coverage."""
    urls = " ".join(u for u, _c, _n in FEED_REGISTRY)
    for gone in ("feeds.reuters.com",
                 "moneycontrol.com/rss",
                 "agriculture.com/rss",
                 "spglobal.com/commodityinsights"):
        assert gone not in urls, f"{gone} failed live and is still listed"


def test_aggregated_items_are_scored_by_the_outlet_not_the_aggregator():
    """A Reuters story reaching us via Google News is still a Reuters story.
    Scoring it as 'Google News' would make every syndicated item look equally
    unknown."""
    from sigbot.providers.news import source_quality

    assert source_quality("Google News https://www.reuters.com/x") == \
        source_quality("Reuters Business")
    assert source_quality("Google News https://blog.nobody.io/y") == DEFAULT_QUALITY
    assert source_quality("Google News") == DEFAULT_QUALITY, (
        "the aggregator itself must never score above an unknown outlet")


def test_google_news_feeds_are_time_bounded():
    """Without a `when:` clause these return years of archive on every poll,
    and the scan would re-read the same stories forever."""
    for url, _c, note in FEED_REGISTRY:
        if "news.google" in url:
            assert "when%3A" in url or "when:" in url, f"{note} has no time bound"


def test_every_category_still_has_two_or_more_sources():
    """One feed for a category is a single point of failure dressed as
    coverage — which is what property became when Moneycontrol 403'd."""
    for category, urls in categories().items():
        assert len(urls) >= 2, f"{category} is down to {len(urls)} source(s)"


def test_every_feed_fetch_has_a_timeout(monkeypatch):
    """`feedparser.parse(url)` does its own fetching with no timeout at all.
    One server that accepts a connection and never replies blocks the whole
    sweep until the task is killed — which is why `news` and `opportunities`
    both failed three times in a row while every feed answered fine to a
    browser."""
    import urllib.request

    seen: list[float | None] = []

    def fake_open(request, timeout=None):
        seen.append(timeout)
        raise TimeoutError("no answer")

    _fake_feedparser(monkeypatch, lambda url: ([], 0))
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)

    from sigbot import skips
    from sigbot.providers.news import RSSProvider

    skips.reset()
    RSSProvider(feeds=["https://slow.example/rss"]).fetch(
        datetime.now(timezone.utc) - timedelta(hours=24))

    assert seen and all(t is not None and t > 0 for t in seen), (
        "a fetch without a timeout can block forever")
    assert skips.report("news_feeds", 0).skipped == 1


def test_the_worst_case_sweep_fits_inside_the_job_timeout():
    """39 feeds that all hang must still finish before the scheduler kills the
    task, or a single bad day looks like a broken job."""
    from sigbot.providers.news import DEFAULT_FEEDS, FEED_TIMEOUT
    from sigbot.scheduler import Task

    job_timeout = Task("news", lambda: None,
                       __import__("datetime").timedelta(hours=2)).timeout
    worst_case = len(DEFAULT_FEEDS) * FEED_TIMEOUT
    assert worst_case < job_timeout, (
        f"{len(DEFAULT_FEEDS)} feeds at {FEED_TIMEOUT}s is {worst_case}s, "
        f"beyond the {job_timeout}s the job is given")


def test_a_feed_that_streams_forever_is_capped():
    """Unbounded output is the same failure as a hang, arriving slowly."""
    from sigbot.providers.news import FEED_MAX_BYTES

    assert 0 < FEED_MAX_BYTES <= 10_000_000
