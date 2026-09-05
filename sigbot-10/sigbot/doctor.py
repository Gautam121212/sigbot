"""Health check — is this actually working?

Run `python -m sigbot.doctor` at any point. It checks the things that have
actually gone wrong, not a generic list, and every failure comes with the exact
command that fixes it.

Each check is one of:

    OK    working
    WARN  will work, but something will bite you later
    FAIL  broken now; the fix is on the next line

The macOS-specific checks exist because two of them are invisible until they
cost you a day. A scheduled job cannot read `~/Downloads` or `~/Documents`
without Full Disk Access, so it fails silently every night; and a file unzipped
from a browser carries a quarantine flag that makes Python refuse parts of it.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

OK, WARN, FAIL = "OK", "WARN", "FAIL"
ROOT = Path(__file__).resolve().parent.parent

# Folders macOS guards. A launchd or cron job reading these needs Full Disk
# Access, and without it the job fails with a permission error nobody sees.
TCC_PROTECTED = ("Downloads", "Documents", "Desktop")


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def render(self) -> str:
        mark = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}[self.status]
        out = f"[{mark}] {self.name}\n         {self.detail}"
        if self.fix:
            out += f"\n         fix: {self.fix}"
        return out


def check_python() -> Check:
    v = sys.version_info
    if v < (3, 10):
        return Check("Python version", FAIL, f"running {v.major}.{v.minor}",
                     "install Python 3.10 or newer from python.org")
    return Check("Python version", OK, f"{v.major}.{v.minor}.{v.micro}")


def check_venv() -> Check:
    """Only a failure if the packages are missing too.

    On macOS, installing without a virtual environment fails outright with
    externally-managed-environment, so in practice no venv means no packages.
    But if the packages are somehow there, the thing runs, and calling that a
    failure would send you chasing a problem you do not have.
    """
    if sys.prefix != sys.base_prefix:
        return Check("Virtual environment", OK, Path(sys.prefix).name)
    import importlib

    if all(_importable(importlib, m) for m in ("numpy", "pandas", "sklearn")):
        return Check("Virtual environment", WARN,
                     "not active, but the packages are installed anyway",
                     "for a clean setup: source .venv/bin/activate")
    return Check("Virtual environment", FAIL, "not active, and packages are missing",
                 "run: source .venv/bin/activate")


def check_packages() -> Check:
    import importlib

    missing, versions = [], []
    for mod, label in (("numpy", "numpy"), ("pandas", "pandas"),
                       ("sklearn", "scikit-learn"), ("pytest", "pytest")):
        try:
            m = importlib.import_module(mod)
            versions.append(f"{label} {getattr(m, '__version__', '?')}")
        except ImportError:
            missing.append(label)
    if missing:
        return Check("Core packages", FAIL, f"missing {', '.join(missing)}",
                     "run: pip install -r requirements.txt")
    return Check("Core packages", OK, ", ".join(versions))


def check_live_packages() -> Check:
    import importlib

    missing = [n for n in ("yfinance", "feedparser")
               if not _importable(importlib, n)]
    if missing:
        return Check("Live data packages", WARN,
                     f"missing {', '.join(missing)} — offline steps still work",
                     "run: pip install -r requirements.txt")
    return Check("Live data packages", OK, "yfinance and feedparser present")


def _importable(importlib, name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def check_location() -> Check:
    """Four ways a location quietly breaks a scheduled job."""
    if sys.platform != "darwin":
        return Check("Install location", OK, str(ROOT))

    path = str(ROOT)
    move = f"move it: mv '{ROOT}' ~/sigbot   (then work from ~/sigbot)"

    # Wiped on restart. Weeks of record gone with no warning.
    if path.startswith(("/tmp", "/private/tmp", "/var/folders")):
        return Check("Install location", FAIL,
                     "a temporary folder — macOS deletes this, taking your "
                     "record with it", move)

    # iCloud can evict a file to the cloud and leave a stub. A background job
    # then finds the database missing, on a schedule, with nothing to explain it.
    if "Mobile Documents" in path or "com~apple~CloudDocs" in path:
        return Check("Install location", FAIL,
                     "inside iCloud Drive. iCloud can offload files to the cloud "
                     "and leave a placeholder, so the databases vanish mid-run "
                     "and reappear later", move)

    # Unmounts when you unplug it, or when the Mac sleeps.
    if path.startswith("/Volumes/"):
        return Check("Install location", WARN,
                     "on an external volume. If it is unmounted at run time the "
                     "job fails, and some drives sleep on their own", move)

    guarded = [p for p in TCC_PROTECTED if p in ROOT.parts]
    if guarded:
        extra = ("" if guarded[0] == "Downloads" else
                 " If that folder syncs to iCloud, files can also be offloaded.")
        return Check(
            "Install location", WARN,
            f"inside ~/{guarded[0]}, which macOS protects. It works when you run "
            "commands yourself, but a scheduled job will be denied and fail "
            f"silently every night.{extra}", move)

    home = str(Path.home())
    if path.startswith(home):
        return Check("Install location", OK,
                     f"{ROOT} — inside your home folder and not a protected "
                     "subfolder. This is the right place.")
    return Check("Install location", WARN,
                 f"{ROOT} — outside your home folder", move)


def check_quarantine() -> Check:
    """Files unzipped from a browser carry a flag that can block execution."""
    if sys.platform != "darwin":
        return Check("Quarantine flag", OK, "not applicable")
    try:
        out = subprocess.run(["xattr", "-l", str(ROOT)], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:  # handled: the check itself reports that it could not look
        return Check("Quarantine flag", OK, "could not check; usually harmless")
    if "com.apple.quarantine" in out:
        return Check("Quarantine flag", WARN,
                     "macOS marked these files as downloaded from the internet",
                     f"run: xattr -dr com.apple.quarantine '{ROOT}'")
    return Check("Quarantine flag", OK, "clear")


def check_writable() -> Check:
    probe = ROOT / ".doctor_write_test"
    try:
        probe.write_text("x")
        probe.unlink()
    except Exception as exc:  # noqa: BLE001  # handled: returns a Check describing the failure
        return Check("Folder writable", FAIL, f"cannot write here: {exc}",
                     "move the folder to ~/sigbot and try again")
    free_gb = shutil.disk_usage(ROOT).free / 1e9
    if free_gb < 1:
        return Check("Folder writable", WARN, f"only {free_gb:.1f} GB free",
                     "free some space; charts and history need room")
    return Check("Folder writable", OK, f"yes, {free_gb:.0f} GB free")


def check_stray_databases() -> Check:
    """A leftover board silently overrides the screen."""
    stray = sorted(p.name for p in ROOT.glob("*.db"))
    if not stray:
        return Check("Databases", OK, "none yet — expected before the first run")
    wl = ROOT / "watchlist.db"
    if wl.exists():
        try:
            with sqlite3.connect(wl) as con:
                n = con.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        except Exception:  # handled: returns a Check describing the failure
            n = -1
        return Check("Databases", OK, f"{', '.join(stray)} (board holds {n} assets)")
    return Check("Databases", OK, ", ".join(stray))


def check_board() -> Check:
    wl = ROOT / "watchlist.db"
    if not wl.exists():
        return Check("The board", WARN, "not built yet",
                     "run: python scripts/run_screen.py --provider yahoo --apply")
    try:
        with sqlite3.connect(wl) as con:
            rows = con.execute("SELECT reason, COUNT(*) FROM watchlist "
                               "GROUP BY reason").fetchall()
    except Exception as exc:  # noqa: BLE001  # handled: returns a Check describing the failure
        return Check("The board", FAIL, f"unreadable: {exc}",
                     "delete watchlist.db and re-run the screen")
    total = sum(c for _, c in rows)
    if total == 0:
        return Check("The board", WARN, "empty",
                     "run: python scripts/run_screen.py --provider yahoo --apply")
    if total < 100:
        return Check("The board", WARN, f"{total} assets, expected 100",
                     "re-run the screen; some symbols probably failed to load")
    return Check("The board", OK, f"{total} assets")


def check_ledger() -> Check:
    db = ROOT / "shadow.db"
    if not db.exists():
        return Check("Predictions", WARN, "none made yet",
                     "run: python -m sigbot.runner daily")
    try:
        with sqlite3.connect(db) as con:
            total, done = con.execute(
                "SELECT COUNT(*), COUNT(hit) FROM predictions").fetchone()
    except Exception as exc:  # noqa: BLE001  # handled: returns a Check describing the failure
        return Check("Predictions", FAIL, f"unreadable: {exc}",
                     "delete shadow.db to start the record again")
    if total == 0:
        # A day where every asset correctly held produces no predictions. That
        # is the system working, not the job failing, so check whether it ran.
        try:
            from .shadow import ShadowLedger

            last = ShadowLedger(str(db)).last_run("daily")
        except Exception:  # noqa: BLE001  # handled: returns a Check describing the failure
            last = None
        if last:
            when = last["ran_at"][:16].replace("T", " ")
            return Check("Predictions", OK,
                         f"daily last ran {when} UTC and held on everything "
                         f"({last.get('note', '')}). No signal is the usual outcome.")
        return Check("Predictions", WARN, "the daily job has never run",
                     "run: python -m sigbot.runner daily")
    if done == 0:
        return Check("Predictions", OK,
                     f"{total} made, none checked yet — they resolve tomorrow")
    return Check("Predictions", OK, f"{total} made, {done} checked against outcomes")


def check_report() -> Check:
    page = ROOT / "app" / "sigbot-report.html"
    if not page.exists():
        return Check("The page", WARN, "not built yet",
                     "run: python -m sigbot.runner publish")
    text = page.read_text(encoding="utf-8", errors="replace")
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(
        page.stat().st_mtime, timezone.utc)
    if "SAMPLE DATA" in text:
        return Check("The page", WARN,
                     "still the shipped sample — these are not your numbers",
                     "run: python -m sigbot.runner publish")
    if "<script" in text.lower():
        return Check("The page", FAIL,
                     "contains JavaScript, so it will be blank on an iPhone",
                     "rebuild it: python -m sigbot.runner publish")
    if age > timedelta(days=2):
        return Check("The page", WARN, f"built {age.days} days ago",
                     "run: python -m sigbot.runner publish")
    return Check("The page", OK,
                 f"built {int(age.total_seconds() // 3600)}h ago, no JavaScript")


def check_network() -> Check:
    """One real download. Everything downstream depends on this working."""
    try:
        import yfinance  # noqa: F401
    except ImportError:
        return Check("Market data", WARN, "yfinance not installed",
                     "run: pip install -r requirements.txt")
    try:
        from .providers.market import YahooProvider

        bars = YahooProvider(retries=1).history("AAPL", "2026-01-01", "2030-01-01")
        return Check("Market data", OK, f"reached Yahoo, {len(bars)} bars for AAPL")
    except Exception as exc:  # noqa: BLE001  # handled: returns a Check describing the failure
        return Check("Market data", FAIL, f"{type(exc).__name__}: {str(exc)[:80]}",
                     "check the internet; if it says rate limit, wait 10 minutes")


def check_schedule() -> Check:
    if sys.platform != "darwin":
        return Check("Automation", WARN, "not macOS; use cron")
    plist = Path.home() / "Library" / "LaunchAgents" / "com.sigbot.daily.plist"
    if not plist.exists():
        return Check("Automation", WARN, "not scheduled — you are running it by hand",
                     "run: bash scripts/schedule.sh")
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=10).stdout
        loaded = "com.sigbot.daily" in out
    except Exception:  # handled: returns a Check describing the failure
        loaded = False
    if not loaded:
        return Check("Automation", WARN, "the schedule exists but is not loaded",
                     f"run: launchctl load '{plist}'")
    return Check("Automation", OK, "scheduled and loaded")


CHECKS = (check_python, check_venv, check_packages, check_live_packages,
          check_location, check_quarantine, check_writable, check_stray_databases,
          check_board, check_ledger, check_report, check_schedule)


def run(include_network: bool = True) -> list[Check]:
    checks = [c() for c in CHECKS]
    if include_network:
        checks.insert(4, check_network())
    return checks


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    offline = "--offline" in argv
    print(f"Checking {ROOT}\n")
    results = run(include_network=not offline)
    for c in results:
        print(c.render())

    fails = [c for c in results if c.status == FAIL]
    warns = [c for c in results if c.status == WARN]
    print("\n" + "-" * 60)
    if fails:
        print(f"{len(fails)} problem(s) to fix before this will work:")
        for c in fails:
            print(f"  - {c.name}: {c.fix or c.detail}")
        return 1
    if warns:
        print(f"Working, with {len(warns)} thing(s) worth doing:")
        for c in warns:
            print(f"  - {c.name}: {c.fix or c.detail}")
        return 0
    print("Everything checks out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
