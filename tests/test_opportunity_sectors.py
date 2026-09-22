"""The 20 opportunity sector cards."""
from __future__ import annotations

from sigbot.opportunity_sectors import (
    SECTORS, assign_sector, build_sector_cards, to_rows,
)
from sigbot.ventures import Venture


def _v(title, thesis, up=6.0, p=0.3, ev=0.4, capped=True):
    return Venture(title, thesis, up, p, ev, capped, ())


def test_there_are_twenty_sector_cards_always():
    assert len(SECTORS) == 20
    cards = build_sector_cards([_v("Tape plant", "factory in Manila")])
    assert len(cards) == 20, "all 20 shown, even empty ones"


def test_ventures_route_to_the_right_sector():
    assert assign_sector(_v("Tape-manufacturing plant", "low-cost factory")) == "Manufacturing"
    assert assign_sector(_v("Dubai property", "residential real estate")) == "Real Estate"
    assert assign_sector(_v("Solar farm", "power plant, feed-in tariff")) == "Energy and Utilities"
    assert assign_sector(_v("Boutique hotel", "resort tourism")) == "Hospitality and Tourism"


def test_a_sector_with_worth_taking_ventures_reads_higher_than_an_empty_one():
    cards = {c.sector: c for c in build_sector_cards([
        _v("Factory", "manufacturing plant", up=8.0, p=0.4, ev=0.5)])}
    assert cards["Manufacturing"].readiness > cards["Aerospace"].readiness
    assert cards["Aerospace"].readiness == 0.0


def test_risky_ventures_are_counted_and_labelled_not_hidden():
    cards = {c.sector: c for c in build_sector_cards([
        _v("Risky factory", "manufacturing plant", up=6.0, p=0.3, ev=0.3)])}
    m = cards["Manufacturing"]
    assert m.risky >= 1
    assert len(m.ventures) == 1, "the risky venture is present, not filtered out"


def test_rows_carry_every_card_and_its_ventures():
    rows = to_rows(build_sector_cards([_v("Factory", "manufacturing plant")]))
    assert len(rows) == 20
    manu = next(r for r in rows if r["sector"] == "Manufacturing")
    assert manu["ventures"] and "verdict" in manu["ventures"][0]


def test_the_twenty_cards_render_on_the_opportunity_page(tmp_path, monkeypatch):
    """The data existed but was never wired into the page — the reason the user
    saw no cards. The opportunity page must now show all 20."""
    import json

    from sigbot.export_app import _attach_sectors

    monkeypatch.chdir(tmp_path)
    from sigbot.opportunity_sectors import build_sector_cards, to_rows
    from sigbot.ventures import Venture
    vs = [Venture("Tape plant", "manufacturing factory", 6.0, 0.3, 0.4, True, ())]
    (tmp_path / "opportunity_sectors.json").write_text(
        json.dumps({"sectors": to_rows(build_sector_cards(vs))}))

    models = _attach_sectors([{"id": "opportunity"}])
    assert len(models[0]["sector_cards"]) == 20

    from sigbot.report import _sector_rows
    html = _sector_rows(models[0])
    assert "Manufacturing" in html and "readiness" in html
