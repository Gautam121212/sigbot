"""Tests for the static report.

`test_no_javascript_anywhere` is the one that matters: it encodes the bug that
made the first app show a title bar and nothing else on an iPhone.
"""
from __future__ import annotations

import json
import re


def _page(html_text: str, page_id: str) -> str:
    """Whole page block: everything until the next page or the nav bar."""
    m = re.search(rf'id="{re.escape(page_id)}">(.*?)(?=<div class="page"|<nav)',
                  html_text, re.S)
    assert m, f"page {page_id} not found"
    return m.group(1)

import pytest


def _all_board(data: dict) -> list[dict]:
    """Every slot, measured or waiting.

    The board splits into `assets` (enough checks to colour) and `waiting`
    (still accumulating). A test about all hundred must read both, or it
    silently checks nothing on a fresh board.
    """
    board = data["board"]
    return list(board.get("assets", [])) + list(board.get("waiting", []))

from sigbot.export_app import build_export, write_export
from tests.conftest import write_records
from sigbot.report import build_report, write_report
from sigbot.shadow import ShadowLedger


@pytest.fixture
def report(tmp_path):
    led = ShadowLedger(tmp_path / "s.db")
    for model, sym, p, n in [("contagion", "AVGO", 0.67, 210),
                             ("news", "NVDA", 0.55, 40),
                             ("daily", "SPY", 0.49, 8)]:
        write_records(led, model, sym, n, p)
    data = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    return build_report(data), data


def test_no_javascript_anywhere(report):
    """iOS Quick Look previews HTML with scripts disabled. Anything drawn by
    JavaScript is invisible there, which is how the first build showed only a
    title bar."""
    h = report[0].lower()
    assert "<script" not in h
    assert "onclick" not in h and "onload" not in h
    assert "javascript:" not in h


def test_every_screen_is_in_the_markup(report):
    h, data = report
    for m in data["models"]:
        assert f'id="m-{m["id"]}"' in h, f"{m['id']} page missing"
        for a in m["alerts"]:
            assert f'id="d-{m["id"]}-{a["symbol"]}"' in h


def test_no_broken_links(report):
    h = report[0]
    targets = set(re.findall(r'class="page" id="([^"]+)"', h)) | {"home"}
    links = set(re.findall(r'href="#([^"]+)"', h))
    assert links <= targets, f"dangling links: {links - targets}"


def test_detail_view_has_all_four_parts(report):
    h = report[0]
    for section in ("Where the number comes from", "What we are actually measuring",
                    "What this will not tell you", "What to do about it"):
        assert section in h, f"missing section: {section}"
    assert "Worst case, realistically" in h
    assert "Risk per position" in h


def test_strong_record_calls_buy_and_weak_one_holds(report):
    h, _ = report
    assert ">BUY<" in _page(h, "d-contagion-AVGO")
    assert ">HOLD<" in _page(h, "d-daily-SPY"), "8 records must not produce a BUY"


def test_thin_evidence_risks_nothing(report):
    h = report[0]
    spy = _page(h, "d-daily-SPY")
    assert "0.00%" in spy
    assert "not enough to tell a real edge from luck" in spy or "no better than a coin" in spy


def test_sizing_never_exceeds_the_cap(report):
    for pct in re.findall(r'<dd[^>]*>(\d+\.\d\d)%</dd>', report[0]):
        assert float(pct) <= 2.0, f"{pct}% exceeds the 2% cap"


def test_no_fabricated_figures(report):
    """The original ban on "portfolio" existed because the page once invented
    one, with holdings nobody held. There is now a real portfolio — replayed
    from scored predictions at recorded prices — so the guard is re-aimed at
    what it was always for: invented figures, and an empty state that reports
    a return instead of admitting it has not run."""
    h = report[0].lower()
    for banned in ("847", "accuracy"):
        assert banned not in h
    if "paper portfolio" in h:
        assert "not run yet" in h or "round trips" in h, (
            "the paper page must either say it has not run or show a real "
            "replay — never a figure with nothing behind it")


def test_html_is_escaped(tmp_path):
    data = build_export(str(tmp_path / "a.db"), str(tmp_path / "b.db"),
                     str(tmp_path / "c.db"))
    data["models"][0]["name"] = '<img src=x onerror="alert(1)">'
    h = build_report(data)
    assert 'onerror="alert(1)"' not in h
    assert "&lt;img" in h


def test_empty_system_still_renders(tmp_path):
    data = build_export(str(tmp_path / "a.db"), str(tmp_path / "b.db"),
                     str(tmp_path / "c.db"))
    h = build_report(data)
    from sigbot.export_app import MODEL_META

    assert f"0 of {len(MODEL_META)} proven" in h
    assert "Nothing has been checked for this one yet" in h
    assert "<script" not in h.lower()


def test_write_report_roundtrip(tmp_path):
    src = write_export(tmp_path / "data.json", db_path=str(tmp_path / "a.db"),
                       patterns_path=str(tmp_path / "b.db"),
                       watchlist_path=str(tmp_path / "c.db"))
    out = write_report(src, tmp_path / "r.html")
    assert out.exists() and out.stat().st_size > 4000
    assert json.loads(src.read_text())["models"]


# --------------------------------------------------- learned and missed tabs

@pytest.fixture
def feeds(tmp_path):
    from sigbot.shadow import ShadowLedger
    led = ShadowLedger(tmp_path / "f.db")
    write_records(led, "news", "NVDA", 12, 2 / 3)
    data = build_export(str(tmp_path / "f.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    return build_report(data), data


def test_three_tabs_in_the_nav(feeds):
    h = feeds[0]
    assert 'class="nav"' in h
    for target in ("#home", "#learned", "#missed"):
        assert f'href="{target}"' in h


def test_learned_feed_shows_wins_and_misses(feeds):
    h, data = feeds
    hits = [e["hit"] for e in data["learning"]]
    assert any(hits) and not all(hits), "the feed must carry both outcomes"
    for e in data["learning"]:
        assert f'id="learned-{e["id"]}"' in h


def test_missed_feed_is_only_misses(feeds):
    h, data = feeds
    assert data["failures"], "expected some misses"
    ids = {e["id"] for e in data["failures"]}
    wins = {e["id"] for e in data["learning"] if e["hit"]}
    assert not (ids & wins), "a win leaked into the miss feed"
    for e in data["failures"]:
        assert f'id="missed-{e["id"]}"' in h


def test_miss_detail_says_how_far_off(feeds):
    h, data = feeds
    page = _page(h, f"missed-{data['failures'][0]['id']}")
    for label in ("How far off", "Average against us", "Worst single one",
                  "Why it went wrong", "What we do about it"):
        assert label in page, f"missing: {label}"


def test_miss_reasons_are_plain_english(feeds):
    reasons = {e["headline"] for e in feeds[1]["failures"]}
    assert reasons <= {"Went the other way", "Started right, then turned",
                       "Right, but too small", "Gapped overnight", "No clear reason"}


def test_no_jargon_anywhere(feeds):
    """Terms that need a finance degree get skimmed, and a skimmed number is
    worse than no number."""
    low = feeds[0].lower()
    for term in ("wilson", "lower bound", "base rate", "expectancy", "kelly",
                 "brier", "isotonic", "calibrat", "quantile", "geometry", "fdr"):
        assert term not in low, f"jargon leaked into the app: {term}"


def test_feed_pages_are_all_reachable(feeds):
    h = feeds[0]
    targets = set(re.findall(r'class="page" id="([^"]+)"', h)) | {"home"}
    assert set(re.findall(r'href="#([^"]+)"', h)) <= targets


# ------------------------------------------------- grouping and descriptions

@pytest.fixture
def repeats(tmp_path):
    """Same asset, same outcome, many times — the case that used to spam the feed."""
    from sigbot.shadow import ShadowLedger
    led = ShadowLedger(tmp_path / "g.db")
    write_records(led, "news", "NVDA", 30, 0.5)
    write_records(led, "news", "RELIANCE.NS", 6, 0.0)
    data = build_export(str(tmp_path / "g.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    return build_report(data), data


def test_repeats_collapse_into_one_entry(repeats):
    h, data = repeats
    assert len(data["learning"]) <= 4, "36 checks should not be 36 feed entries"
    nvda = [e for e in data["learning"] if e["symbol"] == "NVDA"]
    assert sum(e["count"] for e in nvda) == 30
    assert len({e["id"] for e in data["learning"]}) == len(data["learning"]), "ids must be unique"
    for e in data["learning"]:
        assert f'id="learned-{e["id"]}"' in h


def test_group_reports_the_repeat_count_and_average(repeats):
    e = max(repeats[1]["failures"], key=lambda x: x["count"])
    assert e["count"] > 1
    assert "times" in e["brief"]
    assert e["avg_against_pct"] is not None and e["worst_pct"] is not None
    assert e["first_seen"] <= e["last_seen"]


def test_grouped_detail_lists_each_occurrence(repeats):
    h, data = repeats
    e = max(data["failures"], key=lambda x: x["count"])
    page = _page(h, f"missed-{e['id']}")
    assert "Each time it happened" in page
    assert "Times this repeated" in page
    assert "Worst single one" in page


def test_signal_header_carries_a_description(repeats):
    h, data = repeats
    m = next(m for m in data["models"] if m["id"] == "news")
    a = next(a for a in m["alerts"] if a["symbol"] == "NVDA")
    assert a["description"], "description missing from the export"
    page = _page(h, "d-news-NVDA")
    assert a["description"] in page
    # It must sit inside the header card, under the call.
    call = "BUY" if ">BUY<" in page else "HOLD"
    assert page.index(f">{call}<") < page.index(a["description"])


def test_feed_entries_carry_descriptions(repeats):
    for e in repeats[1]["learning"] + repeats[1]["failures"]:
        if e["symbol"] in ("NVDA", "RELIANCE.NS"):
            assert e["description"], f"{e['symbol']} has no description"


def test_universe_covers_shares_and_crypto():
    from sigbot.config import CRYPTO, DESCRIPTIONS, EQUITIES, UNIVERSE

    assert len(UNIVERSE) >= 50, "too narrow to be worth scanning"
    assert len(EQUITIES) >= 30 and len(CRYPTO) >= 18
    assert len({a.symbol for a in UNIVERSE}) == len(UNIVERSE), "duplicate symbols"
    assert all(a.description for a in UNIVERSE), "every asset needs a description"
    assert any(a.symbol.endswith(".NS") for a in EQUITIES), "no Indian listings"
    assert DESCRIPTIONS["NVDA"] and DESCRIPTIONS["BTC-USD"]


def test_descriptions_are_plain_language():
    from sigbot.config import UNIVERSE

    for a in UNIVERSE:
        assert len(a.description) < 110, f"{a.symbol} description is too long to skim"
        assert not any(t in a.description.lower() for t in
                       ("market cap", "p/e", "eps", "ebitda", "$")), \
            f"{a.symbol} description carries a figure that will go stale"


# ------------------------------------------------------------- the board

@pytest.fixture
def board(tmp_path):
    from sigbot.shadow import ShadowLedger
    led = ShadowLedger(tmp_path / "b.db")
    from sigbot.config import POOL

    for sym, p, n in [("NVDA", 0.65, 150), ("BTC-USD", 0.38, 160), ("SPY", 0.52, 20)]:
        assert sym in {a.symbol for a in POOL}
        write_records(led, "news", sym, n, p)
    data = build_export(str(tmp_path / "b.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    return build_report(data), data


def test_board_is_a_hundred_assets(board):
    b = board[1]["board"]
    assert b["size"] == 100
    assert sum(b["counts"].values()) == 100


def test_board_tab_exists_and_links(board):
    h = board[0]
    assert 'href="#board"' in h and 'id="board"' in h
    for tab in ("home", "board", "learned", "missed"):
        assert f'href="#{tab}"' in h


def test_every_asset_has_a_colour_and_a_reason(board):
    for a in _all_board(board[1]):
        assert a["flag"] in ("GREEN", "AMBER", "RED", "TESTING")
        assert a["colour"].startswith("#") and a["reason"]
        assert a["flag_label"] in ("Ready to trade", "Risky — watch only",
                                   "Do not trade", "Being tested")


def test_colour_follows_the_record_not_an_opinion(board):
    by_sym = {a["symbol"]: a for a in _all_board(board[1])}
    for sym in ("NVDA", "SPY"):
        assert sym in by_sym, f"{sym} was predicted on but is missing from the board"
    assert by_sym["NVDA"]["flag"] == "GREEN", "a thick strong record should be green"
    # 20 straight wins is still amber: the sample is below the floor where any
    # colour means something. A green here would be the bug.
    # 20 straight wins reads TESTING, not "risky". Below the floor where any
    # colour means something, a negative verdict is as unsupported as a
    # positive one.
    assert by_sym["SPY"]["flag"] == "TESTING", (
        "20 checks is too few for any verdict, including a negative one")
    assert "20 of 25 checks" in by_sym["SPY"]["reason"]
    assert "Forecast and scored every day" in by_sym["SPY"]["reason"]


def test_unchecked_assets_are_testing_not_a_verdict(board):
    unchecked = [a for a in _all_board(board[1]) if a["n"] == 0]
    assert unchecked, "most of a fresh board should be unchecked"
    assert all(a["flag"] == "TESTING" for a in unchecked), (
        "zero checks earns no verdict — 'risky' states a conclusion about "
        "evidence that does not exist")


def test_board_explains_the_colours(board):
    assert "coin flip" in board[1]["board"]["note"]
    assert "queued for replacement" in board[1]["board"]["note"]


# ------------------------------------------------- the loop is actually closed

def test_models_run_on_the_board_not_a_fixed_list(tmp_path):
    """Everything used to iterate UNIVERSE, so the board could rotate all it
    liked while the models carried on predicting the same 55 names."""
    from dataclasses import replace as _replace

    from sigbot.config import POOL, SETTINGS
    from sigbot.runner import board_assets
    from sigbot.watchlist import Watchlist

    st = _replace(SETTINGS, shadow_db=str(tmp_path / "s.db"),
                  watchlist_db=str(tmp_path / "w.db"))
    cold = board_assets(st)
    assert len(cold) == 55, "cold start should fall back to the universe"

    Watchlist(st.watchlist_db).seed(POOL)
    warm = board_assets(st)
    assert len(warm) == 100, "once seeded, the models must follow the board"
    assert {a.symbol for a in warm} != {a.symbol for a in cold}


def test_cycle_drops_and_replaces_one_or_two(tmp_path):
    from dataclasses import replace as _replace

    from sigbot.config import POOL, SETTINGS
    from sigbot.runner import run_cycle
    from sigbot.shadow import ShadowLedger
    from sigbot.watchlist import Watchlist

    st = _replace(SETTINGS, shadow_db=str(tmp_path / "s.db"),
                  watchlist_db=str(tmp_path / "w.db"))
    wl = Watchlist(st.watchlist_db)
    wl.seed(POOL)
    led = ShadowLedger(st.shadow_db)
    for sym in wl.symbols()[:8]:
        for i in range(150):
            pid = led.record("daily", sym, "BUY", 0.6, 0.02, 100.0, horizon_hours=-1)
            led.resolve(pid, 103.0 if i % 3 == 0 else 97.0,
                        bar_open=100.0, bar_high=103.5, bar_low=97.0)

    sent: list[str] = []

    class Sink:
        def send(self, text): sent.append(text)

    class Offline:
        def history(self, *a, **k): raise RuntimeError("offline")

    before = set(wl.symbols())
    run_cycle(messenger=Sink(), market=Offline(), settings=st)

    after = set(Watchlist(st.watchlist_db).symbols())
    assert len(after) == 100, "the board must stay full"
    assert len(before - after) <= 2, "at most two leave per cycle"
    assert len(before - after) >= 1, "a 33% record over 150 checks should be dropped"
    assert "dropped" in sent[0] and "Even the most flattering" in sent[0]


def test_cycle_says_so_when_nothing_moves(tmp_path):
    from dataclasses import replace as _replace

    from sigbot.config import POOL, SETTINGS
    from sigbot.runner import run_cycle
    from sigbot.watchlist import Watchlist

    st = _replace(SETTINGS, shadow_db=str(tmp_path / "s.db"),
                  watchlist_db=str(tmp_path / "w.db"))
    Watchlist(st.watchlist_db).seed(POOL)
    sent: list[str] = []

    class Sink:
        def send(self, text): sent.append(text)

    class Offline:
        def history(self, *a, **k): raise RuntimeError("offline")

    run_cycle(messenger=Sink(), market=Offline(), settings=st)
    assert "Nothing moved" in sent[0], "an empty ledger must not move the board"


def test_every_board_asset_gets_a_chart_row(board):
    """No cap: memory is cheap, and a partial board is confusing."""
    import re as _re

    h, data = board
    rows = _re.search(r'id="charts">(.*?)(?=<div class="page"|<nav)', h, _re.S).group(1)
    for a in _all_board(data):
        assert a["symbol"] in rows, f"{a['symbol']} missing from the charts tab"


def test_sample_data_is_labelled_as_sample(tmp_path):
    """A shipped demo page looks identical to your own results otherwise.

    The first live run went daily -> open, skipping publish, so the page that
    opened was a sample build from hours earlier. Nothing on it said so.
    """
    data = build_export(str(tmp_path / "a.db"), str(tmp_path / "b.db"),
                        str(tmp_path / "c.db"), is_sample=True)
    assert data["is_sample"] is True
    html = build_report(data)
    assert "SAMPLE DATA" in html
    assert "runner publish" in html


def test_real_data_carries_no_banner(tmp_path):
    data = build_export(str(tmp_path / "a.db"), str(tmp_path / "b.db"),
                        str(tmp_path / "c.db"))
    assert data["is_sample"] is False
    assert "SAMPLE DATA" not in build_report(data)


def test_the_board_separates_stocks_from_crypto(board):
    """Different hours, different costs, different volatility. One undivided
    wall of a hundred names read as noise; two sections read as two answers."""
    html = board[0]
    assert "Stocks (" in html
    assert "Crypto (" in html


def test_learned_is_titled_top_suggestions(board):
    html = board[0]
    assert "Top suggestions" in html
    assert "What it learned" not in html
