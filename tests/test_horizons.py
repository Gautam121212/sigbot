"""Every model must declare its window and what would prove it wrong."""
from __future__ import annotations

from sigbot.export_app import MODEL_META, build_export
from sigbot.horizons import HORIZONS, horizon_for
from sigbot.report import build_report


def test_every_displayed_model_declares_a_window():
    """A signal without a horizon is unreadable: 'AAPL up' means something
    different over three hours than three months, and a reader who guesses
    wrong judges a correct call as a failure."""
    for model_id in MODEL_META:
        h = horizon_for(model_id)
        assert h.badge and h.badge != "Unclassified", model_id
        assert h.window, model_id


def test_every_model_carries_a_falsifier():
    """A claim that cannot be wrong is not a claim."""
    for model_id in MODEL_META:
        assert len(horizon_for(model_id).falsifier) > 30, model_id


def test_an_unknown_model_is_unclassified_not_defaulted():
    """A wrong horizon is worse than a missing one — it tells the reader to
    act on a timescale nobody verified."""
    h = horizon_for("a-model-that-does-not-exist")
    assert h.badge == "Unclassified"
    assert "not declared" in h.falsifier


def test_the_one_off_model_admits_it_cannot_be_scored():
    """Opportunities covers single events. Inventing a test that could never
    be run would be worse than saying so."""
    assert "happens once" in HORIZONS["opportunity"].falsifier


def test_badges_and_falsifiers_reach_the_page(tmp_path):
    html = build_report(build_export(str(tmp_path / "a.db"),
                                     str(tmp_path / "b.db"),
                                     str(tmp_path / "c.db")))
    assert "What would prove this wrong" in html
    assert "Trade · next session" in html
    assert "Thesis · weeks to months" in html
