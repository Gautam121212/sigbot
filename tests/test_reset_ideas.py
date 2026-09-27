"""reset-ideas — start the ideas/opportunity model fresh, leave others intact."""
import sqlite3
from contextlib import closing


def test_reset_ideas_clears_only_ideas(tmp_path, monkeypatch):
    db = tmp_path / "ledger.db"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE predictions (model TEXT, symbol TEXT)")
        con.executemany("INSERT INTO predictions VALUES (?,?)", [
            ("opportunity", "IDEA1"), ("opportunity", "IDEA2"),
            ("stocks", "AAPL"), ("news", "MSFT"), ("crypto", "BTC")])
        con.commit()
    monkeypatch.chdir(tmp_path)

    class S:
        shadow_db = str(db)

    from sigbot.runner import run_reset_ideas
    run_reset_ideas(S())

    with closing(sqlite3.connect(db)) as con:
        rows = dict(con.execute(
            "SELECT model, COUNT(*) FROM predictions GROUP BY model").fetchall())
    assert "opportunity" not in rows          # ideas gone
    assert rows.get("stocks") == 1            # others kept
    assert rows.get("news") == 1
    assert rows.get("crypto") == 1


def test_reset_ideas_clears_state_files(tmp_path, monkeypatch):
    (tmp_path / "opportunities.json").write_text("[]")
    (tmp_path / "opportunity_sectors.json").write_text("{}")
    db = tmp_path / "ledger.db"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE predictions (model TEXT, symbol TEXT)")
        con.commit()
    monkeypatch.chdir(tmp_path)

    class S:
        shadow_db = str(db)

    from sigbot.runner import run_reset_ideas
    run_reset_ideas(S())
    assert not (tmp_path / "opportunities.json").exists()
    assert not (tmp_path / "opportunity_sectors.json").exists()
