"""Tests for the rolling 100.

The load-bearing ones are `test_never_drops_on_a_thin_sample` and
`test_a_good_asset_survives_a_bad_patch`. Rotation that fires on short-run
results manufactures survivorship bias by design; these encode the defence.
"""
from __future__ import annotations

import pytest

from sigbot.config import DESCRIPTIONS, POOL
from sigbot.stats import wilson_interval
from sigbot.watchlist import RULES, Flag, Rules, Watchlist, classify


@pytest.fixture
def wl(tmp_path):
    return Watchlist(tmp_path / "w.db")


# ---------------------------------------------------------------- colours

def test_no_colour_without_evidence():
    flag, why = classify(0, 0)
    assert flag is Flag.TESTING, ("an asset with no checks has earned no "
                                  "verdict, and 'risky' is a verdict")
    assert "Forecast and scored every day" in why
    assert classify(10, 9)[0] is Flag.TESTING, (
        "10 checks proves nothing, including that it is risky")


def test_green_needs_a_thick_record_and_a_clear_floor():
    assert classify(120, 76)[0] is Flag.GREEN          # 63%, floor clears 55%
    assert classify(40, 26)[0] is Flag.AMBER, "65% over 40 checks is still too thin"
    assert classify(200, 112)[0] is Flag.AMBER, "56% floor sits under the bar"


def test_red_means_even_the_best_reading_fails():
    flag, why = classify(150, 60)                      # 40%
    assert flag is Flag.RED
    assert "most flattering reading" in why
    _, upper = wilson_interval(60, 150, 0.90)
    assert upper < RULES.drop_max_upper


def test_never_drops_on_a_thin_sample():
    """A useful asset reads badly over 20 checks often enough that dropping on
    it is firing someone for a bad fortnight."""
    for n in (20, 40, 60, 99):
        assert classify(n, round(0.40 * n))[0] is not Flag.RED, f"dropped at n={n}"
    assert classify(150, 60)[0] is Flag.RED


def test_a_good_asset_survives_a_bad_patch():
    """True 60% asset having a rough 40 checks at 45% must not be dropped."""
    assert classify(40, 18)[0] is not Flag.RED


def test_colours_carry_labels_and_hexes():
    for f in Flag:
        assert f.label and f.colour.startswith("#")
    assert Flag.GREEN.label == "Ready to trade"
    assert Flag.RED.label == "Do not trade"


# ------------------------------------------------------------------ seed

def test_seeds_to_one_hundred_with_a_mix(wl):
    assert wl.seed(POOL) == 100
    held = set(wl.symbols())
    kinds = {a.kind for a in POOL if a.symbol in held}
    assert kinds >= {"equity", "crypto"}, "one asset class took the whole list"
    counts = {k: sum(1 for a in POOL if a.symbol in held and a.kind == k) for k in kinds}
    assert max(counts.values()) <= 60, f"one class dominates: {counts}"
    assert counts["crypto"] >= 15 and counts["equity"] >= 15, f"unbalanced: {counts}"


def test_pool_is_larger_than_the_list():
    assert len(POOL) > 120, "rotation needs somewhere to go"
    assert len({a.symbol for a in POOL}) == len(POOL)
    assert all(a.description for a in POOL)


def test_seeding_is_idempotent(wl):
    wl.seed(POOL)
    assert wl.seed(POOL) == 0 and len(wl.symbols()) == 100


# -------------------------------------------------------------- rotation

def _records(symbols, n, rate):
    return {s: (n, round(n * rate)) for s in symbols}


def test_rotation_drops_reds_and_backfills(wl):
    wl.seed(POOL)
    before = wl.symbols()
    failing = set(before[:12])
    rec = {s: ((150, 60) if s in failing else (150, 95)) for s in before}
    out = wl.rotate(rec, POOL, DESCRIPTIONS)

    assert len(out["dropped"]) == RULES.max_drops_per_cycle, "churn limit not applied"
    assert out["size"] == 100, "list must stay full"
    assert set(wl.symbols()) != set(before)
    assert "survivorship" in out["note"]


def test_churn_is_capped(wl):
    wl.seed(POOL)
    out = wl.rotate(_records(wl.symbols(), 200, 0.35), POOL, DESCRIPTIONS)
    assert len(out["dropped"]) <= RULES.max_drops_per_cycle, (
        "a board that turns over completely in one cycle is fitting noise")


def test_dropped_names_are_kept_with_their_numbers(wl):
    wl.seed(POOL)
    wl.rotate(_records(wl.symbols(), 150, 0.38), POOL, DESCRIPTIONS)
    grave = wl.graveyard()
    assert grave
    for g in grave:
        assert g["n"] and g["reason"] and g["upper"] is not None


def test_a_dropped_name_cannot_return_immediately(wl):
    wl.seed(POOL)
    dropped = wl.rotate(_records(wl.symbols(), 150, 0.38), POOL, DESCRIPTIONS)["dropped"]
    sym = dropped[0]["symbol"]
    assert wl.add(sym, "equity") is False, "re-adding a fresh failure is chasing noise"


def test_cooldown_can_be_configured(tmp_path):
    w = Watchlist(tmp_path / "c.db", Rules(cooldown_days=0))
    w.add("AAPL", "equity")
    w.drop("AAPL", 150, 0.38, 0.47, "test")
    assert w.add("AAPL", "equity") is True


def test_nothing_drops_when_records_are_empty(wl):
    wl.seed(POOL)
    out = wl.rotate({}, POOL, DESCRIPTIONS)
    assert out["dropped"] == [] and out["size"] == 100


# --------------------------------------------------------------- reporting

def test_review_returns_a_slot_per_member(wl):
    wl.seed(POOL)
    slots = wl.review(_records(wl.symbols(), 120, 0.63), DESCRIPTIONS)
    assert len(slots) == 100
    assert all(s.description for s in slots), "descriptions must reach the board"
    assert all(s.flag is Flag.GREEN for s in slots)


def test_review_sorts_problems_first(wl):
    wl.seed(POOL)
    syms = wl.symbols()
    rec = {s: ((150, 60) if i < 5 else (120, 76)) for i, s in enumerate(syms)}
    slots = wl.review(rec, DESCRIPTIONS)
    assert slots[0].flag is Flag.RED


def test_summary_says_so_when_nothing_is_green(wl):
    wl.seed(POOL)
    assert "Nothing is green yet" in wl.summary({})


# ------------------------------------------- ranked entry and slow rotation

def test_only_one_or_two_leave_per_cycle(wl):
    """Replacing the board in bulk destroys the comparison between an incumbent
    and whatever replaced it."""
    wl.seed(POOL)
    out = wl.rotate(_records(wl.symbols(), 200, 0.30), POOL, DESCRIPTIONS)
    assert len(out["dropped"]) <= 2, f"{len(out['dropped'])} left at once"
    assert RULES.max_drops_per_cycle <= 2
    assert out["size"] == 100, "the slot must be refilled"


def test_the_worst_goes_first(wl):
    wl.seed(POOL)
    syms = wl.symbols()
    rec = {s: (200, 100) for s in syms}
    rec[syms[7]] = (200, 40)      # 20% — clearly finished
    rec[syms[9]] = (200, 76)      # 38% — bad, but less so
    out = wl.rotate(rec, POOL, DESCRIPTIONS)
    assert out["dropped"][0]["symbol"] == syms[7]


def test_new_entrants_come_from_the_ranking(wl):
    """Whatever order the caller ranks by is the order slots are filled in."""
    wl.seed(POOL[:100])
    before = set(wl.symbols())
    rest = [a for a in POOL if a.symbol not in before]
    rec = {s: (200, 100) for s in before}
    rec[wl.symbols()[0]] = (200, 40)
    wl.rotate(rec, rest, DESCRIPTIONS)
    added = set(wl.symbols()) - before
    assert added, "no replacement was admitted"
    assert added <= {a.symbol for a in rest}


def test_rotation_is_repeatable_without_thrashing(wl):
    """Running the cycle repeatedly on a healthy board changes nothing."""
    wl.seed(POOL)
    rec = _records(wl.symbols(), 150, 0.62)
    for _ in range(3):
        out = wl.rotate(rec, POOL, DESCRIPTIONS)
        assert out["dropped"] == []
    assert len(wl.symbols()) == 100


def test_note_states_the_churn_limit(wl):
    wl.seed(POOL)
    out = wl.rotate({}, POOL, DESCRIPTIONS)
    assert "per cycle" in out["note"] and "survivorship" in out["note"]


def test_the_reason_says_how_far_off_it_is():
    """'Needs 25' with no sense of the rate leaves you unable to tell a board
    that is filling from one that has stopped — which is the complaint that
    everything stays amber and never says why."""
    from sigbot.watchlist import classify

    _flag, why = classify(12, 7)
    assert "12 of 25" in why
    assert "13 more" in why
    assert "trading day" in why


def test_a_measurable_but_weak_record_states_the_numbers():
    from sigbot.watchlist import classify

    _flag, why = classify(140, 84)
    assert "140 checks" in why
    assert "Worst case" in why
    assert "%" in why


# ------------------------------------------------------------ two gates

def test_admission_and_colour_are_separate_questions():
    """Admission asks whether an asset has been checked enough for a colour to
    mean anything; the colour then says what those checks show. Conflating them
    produced a board of a hundred amber tiles saying the same thing for months
    — a display carrying no information."""
    from sigbot.watchlist import ADMISSION_CHECKS, admitted

    assert not admitted(0)
    assert not admitted(ADMISSION_CHECKS - 1)
    assert admitted(ADMISSION_CHECKS)


def test_a_waiting_asset_is_still_being_forecast():
    """Not shown is not the same as not running. Its forecasts are made and
    scored; only the colour waits."""
    from sigbot.watchlist import waiting_note

    note = waiting_note(12)
    assert "12 of 25" in note
    assert "still being made and scored" in note
    assert "Learned and Missed" in note


def test_the_board_export_separates_measured_from_waiting(tmp_path):
    from sigbot.export_app import build_export

    board = build_export(str(tmp_path / "s.db"), str(tmp_path / "p.db"),
                         str(tmp_path / "w.db"))["board"]
    assert board["size"] == 100
    assert len(board["assets"]) == 100, "every asset stays on the board"
    assert board["measured_count"] == 0, "none has enough checks yet"
    assert board["waiting_count"] == 100
    assert "Grey means being tested" in board["note"]
    assert all(a["flag"] == "TESTING" for a in board["assets"])


def test_a_raw_hit_rate_never_sets_the_colour():
    """60% of 25 checks has a worst case of 44%. It could be a 42% asset having
    a good fortnight, and colouring it green is how you trade noise."""
    from sigbot.watchlist import Flag, classify

    flag, why = classify(25, 15)          # 60% of 25
    assert flag is not Flag.GREEN
    assert "Worst case" in why
