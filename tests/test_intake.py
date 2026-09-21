"""The intake gate: only what could matter enters the loop."""
from __future__ import annotations

import json

from sigbot.intake import ACT, DROP, LEARN, judge, matches_tradable, theme_instruments
from sigbot.runner import board_assets

ASSETS = board_assets()


def _j(h, **kw):
    return judge(h, tradable=matches_tradable(h, ASSETS), **kw)


def test_recaps_and_opinion_never_enter():
    """A recap of a move already made is in the price by definition."""
    for h in ("Top 10 stocks to watch this week", "Why Nvidia stock is up today",
              "Opinion: the market is too expensive", "Market wrap: indices close higher"):
        assert _j(h).verdict == DROP, h


def test_material_news_about_a_tradable_name_acts():
    for h in ("Apple beats Q3 estimates and raises full-year guidance",
              "Microsoft to acquire gaming studio in $2bn deal",
              "Reliance Industries wins major refinery contract"):
        assert _j(h).verdict == ACT, h


def test_material_events_with_nothing_to_trade_are_kept_to_learn():
    assert _j("Magnitude 7.1 earthquake strikes off Japan coast").verdict == LEARN
    assert _j("M 6.4 - 45 km SW of Tokyo, Japan").verdict == LEARN, "USGS title format"


def test_commodity_shocks_are_traded_through_their_instruments():
    """The first version dropped a Strait of Hormuz story as immaterial."""
    d = _j("Tensions rise in the Strait of Hormuz as tanker traffic halts")
    assert d.verdict == ACT and "USO" in d.instruments
    assert "USO" in theme_instruments("OPEC agrees output cut")


def test_a_proven_unreliable_source_is_demoted_to_learn():
    h = "Apple beats Q3 estimates and raises full-year guidance"
    assert _j(h, source_record=(40, 0.30, 0.50)).verdict == LEARN
    assert _j(h, source_record=(10, 0.30, 0.50)).verdict == ACT, "too few checks to judge"


def test_price_target_does_not_match_target_corporation():
    """One-word names that are ordinary words rely on their ticker."""
    assert not matches_tradable("Analysts lift price target after results", ASSETS)


def test_headlines_match_common_names_not_legal_names():
    """Universe rows carry names like 'Apple Inc. Common Stock'. Without the
    common form, none of the widened names could be matched by name."""
    from sigbot.runner import _common_names

    assert _common_names("Apple Inc. Common Stock") == ("apple",)
    assert _common_names("NVIDIA Corporation Common Stock") == ("nvidia",)
    assert _common_names("Target Corporation Common Stock") == ()


def test_curated_names_are_not_replaced_by_legal_names():
    """Loading the universe first let 'Apple Inc. Common Stock' replace the
    curated entry with its aliases ('apple', 'iphone')."""
    aapl = next(a for a in ASSETS if a.symbol == "AAPL")
    assert "apple" in aapl.match_terms()


def test_news_forecasts_record_their_source():
    """Without the source, no source can ever build a record to be judged by."""
    import inspect

    import sigbot.runner as runner
    src = inspect.getsource(runner.run_news)
    assert 'payload=_json.dumps({"source": src})' in src
    assert "_gate_articles(" in src


def test_learn_items_are_logged_and_act_items_returned(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    import sigbot.runner as runner
    from sigbot.shadow import ShadowLedger
    from sigbot.types import Article

    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)

    def art(t):
        return Article(uid=t[:8], title=t, summary="", url=f"https://x/{t[:6]}",
                       source="wire", published_at=now, ingested_at=now)

    arts = [art("Apple beats Q3 estimates and raises guidance"),
            art("Magnitude 7.1 earthquake strikes off Japan coast"),
            art("Top 10 stocks to watch this week")]
    act, learn = runner._gate_articles(arts, ASSETS, ShadowLedger(str(tmp_path / "s.db")), "news")
    assert [a.title[:5] for a in act] == ["Apple"]
    assert len(learn) == 1
    logged = [json.loads(x) for x in (tmp_path / runner.LEARN_LOG).read_text().splitlines()]
    assert logged[0]["class"] == "shock"
