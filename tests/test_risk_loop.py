"""The risk loop: separate from the learning loop, barbell rule enforced."""
from __future__ import annotations



from sigbot.risk_learning import record_risky_bet, verdicts


def _log(path, model, cat, capped, pct, mult, n=1):
    for _ in range(n):
        record_risky_bet(model, cat, downside_capped=capped,
                         amount_risked_pct=pct, outcome_multiple=mult, path=str(path))


def test_a_paying_risk_category_is_recognised(tmp_path):
    p = tmp_path / "r.jsonl"
    _log(p, "opportunity", "venture", True, 0.02, 0.5, n=40)
    v = {x.category: x for x in verdicts(str(p))}["venture"]
    assert v.verdict.startswith("PAYS")


def test_an_uncapped_category_is_never_worth_taking_whatever_the_average(tmp_path):
    """Even a category averaging huge gains is NEVER if any bet was uncapped —
    one unbounded loss ends the game."""
    p = tmp_path / "r.jsonl"
    _log(p, "opportunity", "wild", False, 0.02, 5.0, n=40)   # +5x average!
    v = {x.category: x for x in verdicts(str(p))}["wild"]
    assert v.verdict.startswith("NEVER")


def test_bets_too_large_to_survive_are_never_worth_taking(tmp_path):
    p = tmp_path / "r.jsonl"
    _log(p, "stocks", "oversize", True, 0.20, 0.5, n=40)   # 20% of capital each
    v = {x.category: x for x in verdicts(str(p))}["oversize"]
    assert v.verdict.startswith("NEVER")


def test_too_few_outcomes_is_never_a_verdict(tmp_path):
    p = tmp_path / "r.jsonl"
    _log(p, "opportunity", "venture", True, 0.02, 0.5, n=5)
    v = {x.category: x for x in verdicts(str(p))}["venture"]
    assert v.verdict == "TOO EARLY"


def test_the_risk_loop_touches_nothing_in_edge_measurement():
    """The separation that matters: no import of the ledger, benchmarks, or
    promotion — a lucky risky outcome can never inflate the measured edge."""
    import ast
    import inspect

    import sigbot.risk_learning as rl
    tree = ast.parse(inspect.getsource(rl))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)
    for forbidden in ("shadow", "ledger", "benchmarks", "promotion", "calibration",
                      "paper", "alignment"):
        assert not any(forbidden in name for name in imported), (
            f"the risk loop must not import {forbidden}")


def test_every_model_can_log_to_the_one_risk_loop(tmp_path):
    """It spans all models, not just opportunities."""
    p = tmp_path / "r.jsonl"
    _log(p, "stocks", "thin-setup", True, 0.01, 0.3, n=1)
    _log(p, "crypto15m", "breakout", True, 0.01, -0.5, n=1)
    _log(p, "opportunity", "venture", True, 0.02, 2.0, n=1)
    models = {v.model for v in verdicts(str(p))}
    assert models == {"stocks", "crypto15m", "opportunity"}
