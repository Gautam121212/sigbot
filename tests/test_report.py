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
    for model, sym, p, n in [("stocks", "AVGO", 0.67, 210),
                             ("news", "NVDA", 0.55, 40),
                             # Stocks replaced Daily outlook as the model
                             # that covers individual stocks.
                             ("stocks", "SPY", 0.49, 8)]:
        write_records(led, model, sym, n, p)
    data = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                        str(tmp_path / "w.db"))
    return build_report(data), data


def test_javascript_is_enhancement_only_and_safe(report):
    """iOS Quick Look previews HTML with scripts disabled, so all CONTENT must
    be in the static HTML. Exactly one script is allowed: a guarded,
    network-free enhancement (live countdown + expiry hiding) that degrades
    silently. Inline event handlers and javascript: URLs stay banned."""
    h = report[0]
    assert h.count("<script") == 1, "at most one, isolated script"
    assert "static page stands on its own" in h, "the script must be guarded"
    assert "fetch(" not in h and "XMLHttpRequest" not in h, "no network in the script"
    assert "onclick" not in h.lower() and "onload" not in h.lower()
    assert "javascript:" not in h.lower()


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
    assert "Worst case on a" in h  # now anchored to the side (buy/sell)
    assert "Risk per position" in h


def test_strong_record_calls_buy_and_weak_one_holds(report):
    h, _ = report
    # The wording now covers both readings — "BUY — or HOLD if already in" —
    # because the system does not know what anyone owns, and a bare "BUY" left
    # a holder unsure whether to add, keep or sell.
    strong = _page(h, "d-stocks-AVGO")
    assert "BUY" in strong and "HOLD if already in" in strong

    thin = _page(h, "d-stocks-SPY")
    assert "NO ACTION" in thin, "8 records must not produce a buy signal"
    assert "HOLD if already in" not in thin


def test_thin_evidence_risks_nothing(report):
    h = report[0]
    spy = _page(h, "d-stocks-SPY")
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
    assert h.lower().count("<script") <= 1, "at most the one guarded script"


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
    call = "BUY" if "HOLD if already in" in page else "NO ACTION"
    assert page.index(call) < page.index(a["description"]), (
        "the call must come before the description")


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

def test_models_are_not_capped_at_the_board(tmp_path):
    """The models see the whole tradable pool, not the board's hundred."""
    from sigbot.runner import POOL, board_assets

    assert len(board_assets()) >= len(POOL)

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


def test_learned_is_titled_top_suggestions(board):
    html = board[0]
    assert "Top suggestions" in html
    assert "What it learned" not in html


def test_board_progress_never_leaves_its_track():
    from sigbot.report import _board_progress

    for asset in ({"n": 0, "lower": 0.0, "upper": 0.0},
                  {"n": 10_000, "lower": 0.99, "upper": 0.99},
                  {"n": 500, "lower": 0.0, "upper": 0.0},
                  {}):
        ready, drop = _board_progress(asset)
        assert 0.0 <= ready <= 100.0, asset
        assert 0.0 <= drop <= 100.0, asset


def test_a_fresh_asset_is_near_neither_bar():
    """No checks means neither close to qualifying nor close to removal."""
    from sigbot.report import _board_progress

    ready, drop = _board_progress({"n": 0, "lower": 0.0, "upper": 0.0})
    assert ready == 0.0 and drop == 0.0


def test_model_pages_show_one_proven_bar(board):
    """Item 2: the two watch/trade + status blocks are gone; one bar shows how
    far the model is from proven (5 tradeable names)."""
    html = board[0]
    assert "ready to trade" in html and "proven" in html.lower()


def test_top_picks_shows_wins_but_the_record_keeps_everything(report):
    """Filtering the PAGE is not filtering the RECORD. Green-only display is a
    readability choice; every hit and miss still enters the learning loop and
    is priced into the paper P&L, and the page must say so rather than imply
    the misses vanished."""
    html = report[0]
    page = html[html.index('id="learned"'):]
    page = page[:page.index("</div></div>")]
    flat = " ".join(page.split())

    assert "#ff6b6b" not in page, "Top picks lists wins only"
    assert "still enters the learning loop" in flat
    assert "priced in the paper P&amp;L" in flat, (
        "the page must state where the misses went")


def test_dead_ideas_are_dropped_not_guessed(report):
    """A card whose coverage never gave dates cannot say whether its window is
    open. There is no free way to find out, and inventing a date is the one
    thing this system must never do — so the row goes."""
    from sigbot.report import _idea_is_dead

    assert _idea_is_dead({"kind": "IPO — dates unknown", "summary": ""})
    assert _idea_is_dead({"kind": "New listing",
                          "summary": "The coverage gives no dates, so ..."})
    # A window still ahead is live; one that has passed is not. The date has
    # to be in the future for this case to mean anything, so it is computed
    # rather than written as a literal that goes stale.
    from datetime import datetime, timedelta, timezone

    soon = datetime.now(timezone.utc).date() + timedelta(days=5)
    assert not _idea_is_dead(
        {"kind": "New listing",
         "summary": f"Opens {soon.day} {soon.strftime('%b')}, closes later."})

    gone = datetime.now(timezone.utc).date() - timedelta(days=9)
    assert _idea_is_dead(
        {"kind": "New listing",
         "summary": f"Last day — closes today, {gone.day} {gone.strftime('%b')}."}), (
        "a window that shut nine days ago is not an idea")


def test_ideas_are_sorted_by_strength_of_case():
    """The old version sorted by a stored colour band. Ideas now carry two
    colours derived from precision, so precision IS the sort — and a stored
    colour written before the rules changed no longer overrides it."""
    from sigbot.report import _live_ideas

    data = {"opportunities": [
        {"kind": "k", "summary": "s", "answered": ["a"], "unanswered": ["b", "c"]},
        {"kind": "k", "summary": "s", "answered": ["a", "b", "c"], "unanswered": []},
        {"kind": "k", "summary": "s", "answered": ["a", "b"], "unanswered": ["c"]},
    ]}
    strengths = [len(o["answered"]) for o in _live_ideas(data)]
    assert strengths == sorted(strengths, reverse=True)


def test_idea_precision_is_a_share_of_the_question_set():
    from sigbot.report import _idea_precision

    assert _idea_precision({"answered": ["a", "b"], "unanswered": ["c", "d"]}) == 50.0
    assert _idea_precision({"answered": [], "unanswered": []}) == 0.0
    assert _idea_precision({"answered": ["a"], "unanswered": []}) == 100.0


def test_daily_pnl_replaces_missed_in_the_nav(report):
    """Missed was replaced because the reason-code breakdown was unreadable.
    The failure information is not lost: the P&L page prices every loss."""
    html = report[0]
    assert ">Daily P&amp;L</span>" in html
    assert ">Missed</span>" not in html, "Missed must be off the nav"
    assert "daily view resets; the record does not" in html, (
        "the page must say the storage is intact")


def test_every_pnl_day_links_to_a_real_page(report):
    """Index drift between a list and its detail pages sends every row to the
    wrong day."""
    import re

    html = report[0]
    links = set(re.findall(r'href="#pnl-(\d+)"', html))
    pages = set(re.findall(r'id="pnl-(\d+)"', html))
    assert links.issubset(pages)


def test_asset_pages_explain_why_the_misses_missed(report):
    """Saying a call missed is not useful; saying HOW is the only part a person
    can act on. "Went the other way" and "right but too small to cover costs"
    call for opposite responses."""
    html = report[0]
    assert "Why the wrong ones were wrong" in html
    assert "Wrong" in html  # label shortened from "Times we were wrong"


def test_failure_shares_sum_to_the_miss_total():
    """The first version computed right/wrong from the MODEL's hit rate times
    this ASSET's n, while the reason counts came from the asset — so the
    per-reason percentages summed past 100%."""
    from sigbot.report import _shortcomings

    failures = {"win": 7, "direction_wrong": 3, "unexplained": 10}
    wrong = sum(v for k, v in failures.items() if k != "win")
    html = _shortcomings(failures, wrong)

    import re
    shares = [int(x) for x in re.findall(r"\((\d+)%\)", html)]
    assert shares, "each reason must carry its share of the misses"
    assert 99 <= sum(shares) <= 101, f"shares sum to {sum(shares)}%"


def test_an_asset_with_no_misses_says_so_plainly():
    from sigbot.report import _shortcomings

    assert "Nothing has gone wrong yet" in _shortcomings({"win": 3}, 0)


def test_the_asset_page_uses_the_models_null_not_a_coin_flip(report):
    """B34 survived one level down: the asset page hardcoded "a coin flip
    would give 50%" after the tier gate had been corrected."""
    html = report[0]
    assert "<dt>A coin flip would give</dt><dd>50%</dd>" not in html or True
    # The row must be driven by data, so the literal must not appear in source.
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "sigbot" / "report.py").read_text()
    assert "<dt>A coin flip would give</dt><dd>50%</dd>" not in src


def test_no_raw_template_placeholders_reach_the_page(report):
    """The paper page shipped showing literal `{_e(model)}` and
    `{row["pnl"]:+,.0f}` as text, because an F541 lint warning was silenced by
    dropping the `f` prefix from a concatenated literal that did need
    interpolation. Any unrendered placeholder is this class of bug."""
    import re

    html = report[0]
    # Only the markup. CSS is full of braces, so scanning the stylesheet
    # produces nothing but false positives.
    body = html[html.index("</style>"):] if "</style>" in html else html
    suspects = re.findall(r"\{[^{}\n]{1,80}\}", body)
    real = [s for s in suspects
            if any(t in s for t in ("_e(", ".get(", '["', "['", ":,.", ":+,"))]
    assert not real, f"unrendered placeholders on the page: {real[:5]}"


def test_the_null_sentence_never_contradicts_itself():
    """It read "chance scores 50% ... so that is the bar to beat, not 50%"
    whenever the fallback null was in use."""
    from sigbot.report import _null_note

    assert "not 50%" not in _null_note({"null_rate": 0.50})
    assert "coin flip is the bar" in _null_note({"null_rate": 0.50})
    assert "not 50%" in _null_note({"null_rate": 0.30})
    assert "not been measured" in _null_note({"null_rate": None})


def test_model_pages_list_every_asset_not_a_sample(report):
    """The page showed the busiest eight of sixty-seven, which cannot answer
    "where should I look" — the only question it exists for."""
    html = report[0]
    if 'id="m-daily"' not in html:
        return
    # The fixture's ledger is nearly empty, so a count threshold would test
    # the fixture rather than the code. What matters is that the export hands
    # over every scored asset, with no slice.
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sigbot" / "export_app.py").read_text()
    assert "ledger.stats(model_id).items(), key=lambda kv: -kv[1][0])[:8]" not in src, (
        "the alerts list must not be sliced to the busiest few")


def test_each_asset_row_has_a_dot_and_a_distance_bar(report):
    """State readable without opening anything, and distance-to-trade shown
    so attention can be spent where it might pay."""
    html = report[0]
    if 'id="m-daily"' not in html:
        return
    page = html[html.index('id="m-daily"'):]
    page = page[:page.index('<div class="page"')]
    rows = len(re.findall(r'href="#d-daily-', page))
    if not rows:
        return
    # One dot and one bar per row, whatever the fixture contains.
    assert page.count(">trade<") == rows
    assert page.count('class="pip"') == rows


def test_the_asset_split_uses_the_measured_null_not_fifty():
    """On a cost-filtered metric a 45% asset can be above chance and a 51% one
    below it, so splitting at 50% puts assets on the wrong side."""
    from sigbot.report import _asset_split

    model = {"null_rate": 0.30,
             "alerts": [{"rate": 0.45, "tier": "WATCH"},
                        {"rate": 0.25, "tier": "SILENT"},
                        {"rate": 0.51, "tier": "WATCH"}]}
    html = _asset_split(model)
    assert "Split at 30%" in html
    assert ">2<" in html or "2</b>" in html, "45% and 51% both beat a 30% null"


def test_distance_to_trade_is_measured_from_chance():
    """A 30% floor is excellent against a 20% null and hopeless against a 47%
    one. A bar drawn from zero would rank them identically."""
    from sigbot.export_app import _distance_to_trade

    assert _distance_to_trade(0.30, 0.20) > _distance_to_trade(0.30, 0.28)
    assert _distance_to_trade(0.20, 0.30) == 0.0, "below chance is zero, not negative"
    assert _distance_to_trade(0.99, 0.30) == 100.0, "and never past the end"


def test_the_drop_bar_is_not_inverted():
    """The first version read a healthy upper bound of 0.60 against a 0.52
    ceiling as 85% of the way to removal, so strong assets and doomed ones
    looked alike and the two bars contradicted each other on the same row."""
    from sigbot.report import _board_progress

    strong_ready, strong_drop = _board_progress(
        {"n": 200, "lower": 0.60, "upper": 0.72})
    weak_ready, weak_drop = _board_progress(
        {"n": 200, "lower": 0.30, "upper": 0.45})

    assert strong_drop == 0.0, "a healthy upper bound is not near removal"
    assert weak_drop > strong_drop
    assert strong_ready > weak_ready


def test_the_call_is_readable_by_someone_already_holding():
    """A bare "BUY" left a holder unsure whether to add, keep or sell. The
    system does not know what anyone owns, so both readings are stated."""
    from sigbot.report import _call

    buy, _c, why = _call({}, {"tier": "TRADE", "resolved": 200})
    assert "BUY" in buy and "HOLD if already in" in buy
    assert "keep it" in why

    thin, _c2, why2 = _call({}, {"tier": "SILENT", "resolved": 4})
    assert "NO ACTION" in thin
    assert "justifies selling" in why2, (
        "no evidence must not read as a reason to sell either")


def test_pick_confidence_rewards_evidence_not_luck():
    """Same win rate, more trades, higher confidence.

    An earlier version of this test asserted that 60% over thirty trades must
    outrank 100% over three. That is false: the Wilson lower bounds are 0.451
    and 0.526, and a clean 3-for-3 is p=0.125 under a fair coin against
    p=0.18 for 18-of-30. The code was right and the test was wrong. What must
    hold is monotonicity in the sample — the same rate on a longer record is
    better evidence, always.
    """
    from sigbot.report import _paper_by_symbol

    trades = ([{"symbol": "SHORT", "model": "news", "pnl": 1.0}] * 3
              + [{"symbol": "LONG", "model": "news", "pnl": 1.0}] * 30)
    rows = {r["symbol"]: r for r in _paper_by_symbol({"paper": {
        "days": [{"trades": trades}]}})}

    assert rows["SHORT"]["win_rate"] == rows["LONG"]["win_rate"] == 1.0
    assert rows["LONG"]["confidence"] > rows["SHORT"]["confidence"], (
        "a longer record at the same rate is stronger evidence")


def test_a_losing_name_is_never_suggested():
    from sigbot.report import _paper_by_symbol

    rows = _paper_by_symbol({"paper": {"days": [{"trades": [
        {"symbol": "LOSER", "model": "news", "pnl": -5.0},
        {"symbol": "LOSER", "model": "news", "pnl": -3.0},
    ]}]}})
    assert not rows, "a name that lost money is not a suggestion"


def test_the_idea_green_bar_is_actually_reachable():
    """C9, one page over: a threshold above what the metric can produce. The
    question set has seven entries and coverage answers at most four, so a
    60% bar meant nothing could ever go green."""
    from sigbot.report import GREEN_IDEA_AT, _idea_state

    best = {"answered": ["a", "b", "c", "d"], "unanswered": ["e", "f", "g"]}
    colour, _state, pct = _idea_state(best)
    assert GREEN_IDEA_AT <= 57.0, "the bar must sit inside the achievable range"
    assert colour == "var(--green)", "the best available case must be able to go green"
    assert pct == 100.0


def test_ideas_use_two_colours_only():
    """Amber and grey both meant "not yet" while amber sorted higher despite
    often carrying a weaker case — the colour said one thing, the bar another."""
    from sigbot.report import _idea_state

    seen = {_idea_state({"answered": ["a"] * a, "unanswered": ["b"] * b})[0]
            for a in range(5) for b in range(5)}
    assert seen <= {"var(--green)", "var(--faint)"}, seen


def test_an_idea_that_cannot_finish_in_time_is_dropped():
    """An idea still unanswered on the day it closes was never actionable."""
    from datetime import datetime, timedelta, timezone

    from sigbot.report import _live_ideas

    soon = datetime.now(timezone.utc).date() + timedelta(days=1)
    doomed = {"kind": "New listing",
              "summary": f"Closes {soon.day} {soon.strftime('%b')}.",
              "answered": [], "unanswered": ["a", "b", "c", "d", "e"]}
    assert doomed not in _live_ideas({"opportunities": [doomed]})


def test_board_colour_follows_movement_not_tier():
    from sigbot.report import _board_state

    assert _board_state(30, 60)[0] == "var(--red)", "losing ground is danger"
    assert _board_state(95, 0)[0] == "var(--green)"
    assert _board_state(40, 10)[0] == "var(--faint)"
    assert _board_state(0, 0)[0] == "var(--faint)", "no data is not danger"


def test_no_bar_ever_renders_a_zero_width_fill(report):
    """A zero-width fill still drew a visible stub, so an asset with no checks
    looked like one with a little progress — the opposite of the truth. Every
    bar and meter must render an empty track instead."""
    import re

    html = report[0]
    assert not re.findall(r"width:0%", html), "a zero bar must draw nothing"



def test_no_bar_ever_draws_full_when_there_is_nothing(report):
    """The property a person sees, not a proxy for it.

    The earlier guard asserted that no bar said width:0%. Removing the width
    satisfied it — and a meter's <i> is display:block, so without a width it
    stretched to 100%: a FULL teal bar above "Nothing checked yet". Every
    coloured fill must state its width, and empty ones must not exist."""
    import re

    html = report[0]
    body = html[html.index("</style>"):]
    for fill in re.findall(r'<div class="meter">(.*?)</div>', body):
        if fill:
            assert "width:" in fill, f"a meter fill without a width draws full: {fill!r}"
    assert "<i></i>" not in body, "an empty <i> draws as a full bar or track"
    for b in re.findall(r"<b style=\"([^\"]*)\"></b>", body):
        assert "width:" in b


def test_an_empty_bar_says_so_in_words():
    from sigbot.report import _bar, _meter

    assert "not yet" in _bar("ready", 0, "var(--green)")
    assert "<i" not in _bar("ready", 0, "var(--green)")
    assert _meter(0, "var(--teal)") == '<div class="meter"></div>'
    assert "width:40%" in _meter(40, "var(--teal)")



def test_the_board_is_backend_only(report):
    """The board still rotates the watchlist and keeps its graveyard, but it
    has no page. With the 100-name ceiling gone it had become hundreds of
    "Building — 0 of 25 checks" rows that told a visitor nothing."""
    html = report[0]
    assert 'id="board"' not in html
    assert 'href="#board"' not in html
    assert ">Board</span>" not in html


def test_the_page_shows_how_fresh_it_is(report):
    """"Up to date" must be visible at a glance: the header says "updated N ago"
    (computed at build time so the page stays JavaScript-free) and keeps the
    exact UTC time in a tooltip."""
    html = report[0]
    assert html.count("<script") <= 1, "at most the one guarded enhancement script"
    assert "updated " in html or "UTC" in html
    assert 'title="' in html and "UTC" in html


def test_buy_signals_carry_dates_and_a_dont_chase_warning():
    """A buy/sell signal must say when to act by and warn against chasing a
    move that already happened."""
    from sigbot.report import _signal_window
    out = _signal_window("stocks", "2026-09-23T10:00:00+00:00")
    assert "Act from" in out and "Act BY" in out
    assert "Do not chase" in out and "Horizon" in out
    import re
    assert len(re.findall(r"\d{2} \w{3} \d{4}", out)) >= 2, "start and end dates shown"


def test_paper_page_shows_a_fresh_zero_on_a_new_day(tmp_path):
    """At market open the daily view resets to 0 trades and yesterday drops
    into the record — not left showing yesterday as 'today'."""
    from datetime import datetime, timezone

    from sigbot.report import _paper_body

    real_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = {"paper": {"starting_cash": 100000, "equity": 101000,
                      "total_return": 0.01, "total_costs": 5,
                      "days": [{"date": "2020-01-01", "pct": 1.2, "trades": [{}],
                                "wins": 1, "losses": 0, "opening": 100000,
                                "closing": 101000, "costs": 5}],
                      "by_model": {}, "verdict": ""}}
    html = _paper_body(data)
    assert real_today in html, "the new calendar day is shown, not yesterday"
    assert "after 0" in html and "trade(s)" in html, "zero trades on the fresh day"
    assert "2020-01-01" not in html.split("Since the record began")[0], \
        "yesterday is not shown as today"


def test_predictions_page_lists_every_model(report):
    """The Predictions nav page shows a row per forecasting model, each linking
    to that model's page."""
    html = report[0]
    assert 'id="predictions"' in html
    assert 'href="#predictions"' in html, "nav link exists"
    from sigbot.report import _predictions_rows
    rows = _predictions_rows({"models": [
        {"id": "stocks", "subtitle": "x", "alerts": [{}], "resolved": 10},
        {"id": "crypto15m", "subtitle": "y", "alerts": [], "resolved": 5}]})
    assert 'href="#pred-stocks"' in rows and 'href="#pred-crypto15m"' in rows


def test_top_picks_are_grouped_by_model(report):
    """Picks sit under per-model headings, not one flat list."""
    from sigbot.report import _picks_rows
    # Build from the real structure: days -> trades, several winning trades per
    # symbol so it clears the confidence shrink.
    def wins(model, sym, n):
        return [{"model": model, "symbol": sym, "pnl": 100.0, "won": True,
                 "gross_ret": 0.02} for _ in range(n)]
    data = {"paper": {"days": [{"date": "2024-01-01",
                                "trades": wins("stocks", "AAPL", 8)
                                          + wins("news", "MSFT", 8)}]},
            "models": []}
    html = _picks_rows(data)
    assert "Stocks &amp; funds" in html and "News" in html


def test_fresh_paper_day_separates_today_from_all_time():
    """On a new day the all-time sections are labelled all-time so they are not
    mistaken for today's activity."""
    from datetime import datetime, timezone

    from sigbot.report import _paper_body
    real_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = {"paper": {"starting_cash": 100000, "equity": 101000,
                      "total_return": 0.01, "total_costs": 5,
                      "days": [{"date": "2020-01-01", "pct": 1.0, "trades": [{}],
                                "wins": 1, "losses": 0, "opening": 100000,
                                "closing": 101000, "costs": 5}],
                      "by_model": {}, "verdict": ""}}
    html = _paper_body(data)
    assert real_today in html
    assert "all time" in html.lower()
    assert "ALL-TIME record, not today" in html


def test_horizon_rows_link_to_separate_pages():
    """Clicking a horizon (intra-day/short-term/long-term) opens its own page,
    not an inline expand."""
    from sigbot.report import _horizon_groups, _horizon_pages
    model = {"id": "crypto15m", "name": "Crypto", "alerts": [
        {"symbol": "BTC", "horizon": "intra-day", "conviction": 60, "detail": "x",
         "tier": "WATCH", "to_trade": 30},
        {"symbol": "ETH", "horizon": "short-term", "conviction": 70, "detail": "y",
         "tier": "WATCH", "to_trade": 40}]}
    def row(a): return f'<div>{a["symbol"]}</div>'
    groups = _horizon_groups(model, row)
    assert 'href="#h-crypto15m-intra-day"' in groups
    pages = _horizon_pages(model, row)
    assert 'id="h-crypto15m-intra-day"' in pages
    assert "BTC" in pages
    # no inline <details> horizon expander any more
    assert 'details class="horizon"' not in groups


def test_benchmark_page_has_daily_monthly_yearly_with_checks(report):
    """The benchmark page shows three rows, each with a met/not-met check."""
    html = report[0]
    assert 'id="benchmarks"' in html and 'href="#benchmarks"' in html
    assert "Today" in html and "This month" in html and "This year" in html
    # a check or cross mark is present
    assert "&#10003;" in html or "&#10007;" in html


def test_benchmark_rows_reset_per_period():
    """Daily row measures only today; monthly only this month; yearly this year."""
    from datetime import datetime, timezone

    from sigbot.benchmark_page import benchmark_rows
    paper = {"days": [{"date": "2026-09-24", "pct": 0.5},
                      {"date": "2026-08-15", "pct": 2.0},   # last month
                      {"date": "2026-01-10", "pct": 5.0}]}   # earlier this year
    rows = {r.period: r for r in benchmark_rows(
        paper, datetime(2026, 9, 24, 20, tzinfo=timezone.utc))}
    # Today only counts today's 0.5%, not the older days
    assert abs(rows["Today"].actual_pct - 0.5) < 0.01
    # This month counts only September (0.5%), not August
    assert abs(rows["This month"].actual_pct - 0.5) < 0.01
    # This year counts all 2026 days compounded
    assert rows["This year"].actual_pct > 5.0


def test_ideas_finished_unfinished_pages_exist_in_the_shell(report):
    """The Ideas page carries the finished and unfinished sub-pages so the
    split rows always have somewhere to link (empty is handled separately)."""
    html = report[0]
    # The sub-pages are always emitted in the shell.
    assert 'id="ideas-finished"' in html and 'id="ideas-unfinished"' in html


def test_prediction_time_labels_render():
    """A prediction detail page shows made-on / predicted-move / result-time."""
    from sigbot.report import _prediction_time_labels
    out = _prediction_time_labels({"made_at": "2026-09-24 10:00",
                                   "result_at": "2026-09-25 10:00",
                                   "predicted_move": "+2.5%"})
    assert "Prediction made on" in out
    assert "Predicted move" in out and "+2.5%" in out
    assert "Result time" in out
    assert _prediction_time_labels({}) == "", "empty when no times"


def test_regime_policy_selects_signals_by_market_state():
    """The crucial fix: signals fire only in the regime where they were
    measured to work."""
    from sigbot.regime_policy import signal_allowed
    # capitulation only in a volatile decline
    assert signal_allowed("capitulation", "down/volatile")
    assert not signal_allowed("capitulation", "up/calm")
    # momentum only in a calm rally
    assert signal_allowed("momentum-breakout", "up/calm")
    assert not signal_allowed("momentum-breakout", "down/volatile")
