"""GDELT parsing, and a combined source that survives either side failing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sigbot.providers.gdelt import CombinedNewsProvider, GDELTProvider, parse


def test_parses_gdelt_articles_newer_than_since():
    since = datetime(2026, 9, 20, tzinfo=timezone.utc)
    payload = {"articles": [
        {"url": "https://a/1", "title": "OPEC agrees cut", "seendate": "20260921T120000Z",
         "domain": "reuters.com"},
        {"url": "https://a/2", "title": "Old story", "seendate": "20260101T000000Z"},
        {"url": "", "title": "no link", "seendate": "20260921T120000Z"},
        {"url": "https://a/3", "title": "bad date", "seendate": "yesterday"},
    ]}
    arts = parse(payload, since)
    assert [a.title for a in arts] == ["OPEC agrees cut"]
    assert arts[0].source == "reuters.com"
    assert arts[0].published_at == datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def test_an_empty_or_odd_response_is_not_an_error():
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    assert parse({}, since) == [] and parse({"articles": None}, since) == []


def test_the_first_refusal_stops_gdelt_for_the_run(monkeypatch):
    import urllib.request

    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise OSError("unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    out = GDELTProvider(queries=("a", "b"), pause=0).fetch(
        datetime.now(timezone.utc) - timedelta(hours=2))
    # One refusal ends the run's GDELT queries: after a 429 the rest would be
    # refused too, and the RSS feeds carry on regardless.
    assert out == [] and len(calls) == 1


def test_gdelt_failing_never_stops_the_rss_feeds():
    class Works:
        def fetch(self, since):
            from sigbot.types import Article
            now = datetime.now(timezone.utc)
            return [Article("u", "t", "", "https://x", "s", now, now)]

    class Fails:
        def fetch(self, since):
            raise RuntimeError("down")

    out = CombinedNewsProvider([Fails(), Works()]).fetch(datetime.now(timezone.utc))
    assert len(out) == 1


def test_duplicates_across_sources_are_merged():
    class Same:
        def fetch(self, since):
            from sigbot.types import Article
            now = datetime.now(timezone.utc)
            return [Article("u", "t", "", "https://same", "s", now, now)]

    assert len(CombinedNewsProvider([Same(), Same()]).fetch(datetime.now(timezone.utc))) == 1


def test_gdelt_is_polite():
    """GDELT asks for no more than one request every five seconds."""
    from sigbot.providers.gdelt import PAUSE_SECONDS
    assert PAUSE_SECONDS >= 5.0
