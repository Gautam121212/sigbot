"""Tests for phone delivery setup. No network: the transport is stubbed."""
from __future__ import annotations

import json
import urllib.error

import pytest

from sigbot import setup_delivery as sd


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "1234567890:AAHtest")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")


def test_url_carries_token_and_chat(env):
    url = sd.telegram_url()
    assert "bot1234567890:AAHtest/sendMessage" in url
    assert "chat_id=987654321" in url


def test_missing_config_names_the_fix(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(RuntimeError, match="setup_delivery --telegram"):
        sd.telegram_url()


def test_malformed_token_rejected_before_the_request(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "no-colon-here")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with pytest.raises(RuntimeError, match="colon"):
        sd.telegram_url()


def test_send_posts_json(env, monkeypatch):
    seen = {}

    class Resp:
        def read(self): return json.dumps({"ok": True}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=0):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        seen["type"] = req.headers.get("Content-type")
        return Resp()

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)
    assert sd.send("hello")["ok"] is True
    assert seen["body"] == {"text": "hello"}
    assert seen["type"] == "application/json"


@pytest.mark.parametrize("code,fragment", [
    (401, "revoked"),
    (400, "have not messaged the bot"),
    (403, "blocked"),
    (404, "malformed"),
    (429, "rate limited"),
])
def test_each_error_names_the_actual_problem(code, fragment):
    assert fragment in sd.diagnose(code, "detail")


def test_http_error_is_translated(env, monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     __import__("io").BytesIO(b'{"description":"chat not found"}'))

    monkeypatch.setattr(sd.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="have not messaged the bot"):
        sd.send("x")


def test_unreachable_network_is_explained(env, monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(sd.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="could not reach Telegram"):
        sd.send("x")


def test_verify_reports_failure_without_config(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    assert sd.verify() is False
    assert "NOT CONFIGURED" in capsys.readouterr().out


def test_verify_reports_success(env, monkeypatch, capsys):
    monkeypatch.setattr(sd, "send", lambda *a, **k: {"ok": True})
    assert sd.verify() is True
    assert "DELIVERED" in capsys.readouterr().out


def test_steps_cover_the_bot_must_be_messaged_first():
    steps = sd.TELEGRAM_STEPS
    assert "@BotFather" in steps
    # The instruction that was actually missed: message YOUR bot, not BotFather.
    assert "not BotFather" in steps
    assert "This is the step people miss" in steps


def test_cli_modes():
    assert sd.main(["--telegram"]) == 0
    assert sd.main([]) == 2


# --------------------------------------------------- chat id discovery

def _fake_get(monkeypatch, payload):
    class Resp:
        def read(self): return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    seen = {}

    def fake(url, timeout=0):
        seen["url"] = url if isinstance(url, str) else url.full_url
        return Resp()

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)
    return seen


def test_chatid_found_and_printed(env, monkeypatch, capsys):
    _fake_get(monkeypatch, {"ok": True, "result": [
        {"message": {"chat": {"id": 987654321, "first_name": "Gautam"}}}]})
    assert sd.find_chat_id() == 0
    out = capsys.readouterr().out
    assert "987654321" in out and "Gautam" in out
    assert "export TELEGRAM_CHAT_ID" in out


def test_chatid_never_prints_the_token(env, monkeypatch, capsys):
    """The token leaked once via a browser address bar. It must not leak here."""
    _fake_get(monkeypatch, {"ok": True, "result": [
        {"message": {"chat": {"id": 1, "first_name": "x"}}}]})
    sd.find_chat_id()
    assert "AAHtest" not in capsys.readouterr().out


def test_empty_result_explains_every_cause(env, monkeypatch, capsys):
    """This is exactly what the live attempt returned."""
    _fake_get(monkeypatch, {"ok": True, "result": []})
    assert sd.find_chat_id() == 1
    out = capsys.readouterr().out
    assert "BotFather instead of your own bot" in out
    assert "press START" in out or "did not press START" in out
    assert "webhook" in out
    assert "will not reply" in out


def test_chatid_reads_group_and_edited_messages(env, monkeypatch, capsys):
    _fake_get(monkeypatch, {"ok": True, "result": [
        {"edited_message": {"chat": {"id": -100200, "title": "My group"}}}]})
    assert sd.find_chat_id() == 0
    assert "-100200" in capsys.readouterr().out


def test_chatid_requires_a_token(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    assert sd.find_chat_id() == 1
    assert "TELEGRAM_TOKEN is not set" in capsys.readouterr().out


def test_chatid_rejects_a_malformed_token(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_TOKEN", "not-a-token")
    assert sd.find_chat_id() == 1
    assert "colon" in capsys.readouterr().out


def test_clear_webhook(env, monkeypatch, capsys):
    seen = _fake_get(monkeypatch, {"ok": True, "result": True})
    assert sd.clear_webhook() == 0
    assert "deleteWebhook" in seen["url"]
    assert "Webhook cleared" in capsys.readouterr().out


def test_steps_no_longer_send_you_to_a_browser():
    """Pasting a token into an address bar is how one got photographed."""
    steps = sd.TELEGRAM_STEPS
    assert "api.telegram.org" not in steps
    assert "Do not paste it into a browser" in steps
    assert "will never reply" in steps
    assert "--chatid" in steps


def test_cli_exposes_the_new_commands():
    assert sd.main(["--telegram"]) == 0
    assert sd.main([]) == 2


# ------------------------------------------------------- file delivery

def _capture_upload(monkeypatch):
    seen = {}

    class Resp:
        def read(self): return json.dumps({"ok": True}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=0):
        seen["url"] = req.full_url
        seen["ctype"] = req.headers.get("Content-type", "")
        seen["body"] = req.data
        return Resp()

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)
    return seen


def test_send_document_uploads_the_file(env, monkeypatch, tmp_path):
    """Removes the AirDrop step: the report arrives on the phone by itself."""
    page = tmp_path / "report.html"
    page.write_text("<html>the report</html>")
    seen = _capture_upload(monkeypatch)

    assert sd.send_document(page, caption="Today")["ok"] is True
    assert seen["url"].endswith("/sendDocument")
    assert seen["ctype"].startswith("multipart/form-data; boundary=")
    assert b'name="chat_id"' in seen["body"]
    assert b"Today" in seen["body"]
    assert b"<html>the report</html>" in seen["body"]
    assert b'filename="report.html"' in seen["body"]


def test_send_document_needs_both_credentials(monkeypatch, tmp_path):
    page = tmp_path / "r.html"
    page.write_text("x")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "1:AAH")
    with pytest.raises(RuntimeError, match="must both be set"):
        sd.send_document(page)


def test_send_document_translates_a_rejection(env, monkeypatch, tmp_path):
    page = tmp_path / "r.html"
    page.write_text("x")

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {},
            __import__("io").BytesIO(b'{"description":"chat not found"}'))

    monkeypatch.setattr(sd.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="have not messaged the bot"):
        sd.send_document(page)


def test_send_document_is_binary_safe(env, monkeypatch, tmp_path):
    """A 3 MB report with charts must survive the multipart assembly intact."""
    page = tmp_path / "big.html"
    payload = b"\xef\xbb\xbf<svg>" + bytes(range(256)) * 500 + b"</svg>"
    page.write_bytes(payload)
    seen = _capture_upload(monkeypatch)
    sd.send_document(page)
    assert payload in seen["body"]


# ------------------------------------------------------------- file delivery

def _capture(monkeypatch):
    seen = {}

    class Resp:
        def read(self): return json.dumps({"ok": True}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(req, timeout=0):
        seen["url"] = req.full_url
        seen["ct"] = req.headers.get("Content-type")
        seen["body"] = req.data
        return Resp()

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)
    return seen


def test_send_file_uploads_as_multipart(env, monkeypatch, tmp_path):
    """Removes the AirDrop step: the report lands in the same chat as alerts."""
    f = tmp_path / "sigbot-report.html"
    f.write_text("<html>x</html>")
    seen = _capture(monkeypatch)
    assert sd.send_file(f, caption="Board")["ok"] is True
    assert seen["url"].endswith("/sendDocument")
    assert seen["ct"].startswith("multipart/form-data; boundary=")
    assert b'filename="sigbot-report.html"' in seen["body"]
    assert b"Board" in seen["body"]


def test_send_file_needs_both_credentials(monkeypatch, tmp_path):
    f = tmp_path / "a.html"
    f.write_text("x")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "1:AAH")
    with pytest.raises(RuntimeError, match="must both be set"):
        sd.send_file(f)


def test_send_file_refuses_an_oversized_file(env, monkeypatch, tmp_path):
    """Telegram caps uploads at 50 MB; fail before the upload, not after."""
    f = tmp_path / "big.html"
    f.write_bytes(b"x" * (51 * 1024 * 1024))
    with pytest.raises(RuntimeError, match="50 MB"):
        sd.send_file(f)


def test_send_file_translates_a_telegram_error(env, monkeypatch, tmp_path):
    import io as _io

    f = tmp_path / "a.html"
    f.write_text("x")

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     _io.BytesIO(b'{"description":"chat not found"}'))

    monkeypatch.setattr(sd.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="have not messaged the bot"):
        sd.send_file(f)


# ------------------------------------------- one report in the chat at a time

def test_send_report_deletes_the_one_it_replaces(env, monkeypatch, tmp_path):
    """A file already in the chat is a frozen copy. Several of them means the
    one you happen to tap may be hours out of date."""
    seen = []

    class Resp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return json.dumps(self._p).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        seen.append(url)
        if "deleteMessage" in url:
            return Resp({"ok": True})
        return Resp({"ok": True, "result": {"message_id": 555}})

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)
    state = tmp_path / ".last_report"
    state.write_text("444")
    report = tmp_path / "r.html"
    report.write_text("<html>x</html>")

    sd.send_report(report, caption="Board", state_path=state)

    assert any("sendDocument" in u for u in seen)
    assert any("deleteMessage" in u and "message_id=444" in u for u in seen)
    assert state.read_text() == "555", "the new id must be remembered"


def test_first_send_deletes_nothing(env, monkeypatch, tmp_path):
    seen = []

    class Resp:
        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 1}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sd.urllib.request, "urlopen",
                        lambda req, timeout=0: (seen.append(
                            req if isinstance(req, str) else req.full_url), Resp())[1])
    report = tmp_path / "r.html"
    report.write_text("x")
    sd.send_report(report, state_path=tmp_path / ".none")
    assert not any("deleteMessage" in u for u in seen)


def test_a_failed_delete_does_not_block_the_send(env, monkeypatch, tmp_path, capsys):
    """An extra stale copy is worse than tidy. No copy at all is worse than both."""
    class Resp:
        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 9}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        if "deleteMessage" in url:
            raise urllib.error.URLError("network gone")
        return Resp()

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)
    state = tmp_path / ".last"
    state.write_text("100")
    report = tmp_path / "r.html"
    report.write_text("x")

    result = sd.send_report(report, state_path=state)
    assert result["ok"] is True, "the send must succeed even if the delete fails"
    assert "could not remove the previous report" in capsys.readouterr().out


def test_a_corrupt_marker_does_not_fail_the_send(env, monkeypatch, tmp_path):
    class Resp:
        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 7}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sd.urllib.request, "urlopen", lambda req, timeout=0: Resp())
    state = tmp_path / ".last"
    state.write_text("not a number")
    report = tmp_path / "r.html"
    report.write_text("x")
    assert sd.send_report(report, state_path=state)["ok"] is True
    assert state.read_text() == "7"


def test_publish_is_frequent_enough_to_stay_current():
    """Pinning the exact interval made this test fail every time the cadence
    changed, which told us nothing. What matters is that the file on the phone
    is never stale by more than about half an hour."""
    from datetime import timedelta

    from sigbot.coordinator import JOBS

    publish = next(row for row in JOBS if row[0] == "publish")
    assert publish[2] <= timedelta(minutes=30)


def test_the_report_fingerprint_ignores_the_timestamp(tmp_path):
    """Without excluding generated_at, every rebuild differs and the
    send-only-on-change check does nothing at all."""
    from sigbot.runner import _report_fingerprint

    report = tmp_path / "r.html"
    base = '<html><span>2026-08-30 21:00 UTC</span><p>AVGO 84% of 210</p></html>'

    report.write_text(base)
    first = _report_fingerprint(str(report))

    report.write_text(base.replace("21:00", "23:45"))
    assert _report_fingerprint(str(report)) == first, "a clock tick is not a change"

    report.write_text(base.replace("84% of 210", "85% of 211"))
    assert _report_fingerprint(str(report)) != first, "a real change was missed"

    report.write_text(base.replace("AVGO", "NVDA"))
    assert _report_fingerprint(str(report)) != first


# --------------------------------------------- every job reaches the phone

def test_the_default_messenger_includes_telegram(env):
    """Jobs used to write only to console and outbox.log. Under launchd there
    is no terminal, so `daily`, `news` and `opportunities` reached nobody."""
    from sigbot.runner import default_messenger

    sinks = [type(s).__name__ for s in default_messenger().sinks]
    assert "TelegramMessenger" in sinks, "jobs would write to a file nobody reads"


def test_a_long_digest_is_split_not_dropped(env):
    """Telegram rejects anything over 4096 with a 400. A digest that silently
    fails to send is worse than one arriving in two parts."""
    from sigbot.messenger import TelegramMessenger

    tm = TelegramMessenger()
    assert tm._chunks("short") == ["short"]

    long = "\n\n".join(f"paragraph {i} " + "x" * 300 for i in range(30))
    parts = tm._chunks(long)
    assert len(parts) > 1
    assert all(len(p) <= tm.LIMIT for p in parts), "a part still exceeds the cap"
    assert parts[0].startswith("(1/"), "parts must be labelled or they read as duplicates"


def test_telegram_sink_refuses_without_credentials(monkeypatch):
    from sigbot.messenger import TelegramMessenger

    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_TOKEN"):
        TelegramMessenger()


def test_missing_credentials_do_not_break_the_default(monkeypatch):
    """A missing sink must not take the whole run down with it."""
    from sigbot.runner import default_messenger

    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    sinks = [type(s).__name__ for s in default_messenger().sinks]
    assert "ConsoleMessenger" in sinks and "TelegramMessenger" not in sinks


# ----------------------------------------------------- the heartbeat

def test_send_can_be_silent(env, monkeypatch):
    """A heartbeat every half hour must be visible without buzzing the phone —
    a channel that buzzes 48 times a day is the one you mute, and muting it
    takes the real alerts with it."""
    bodies = []

    class Resp:
        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 1}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        bodies.append(json.loads(req.data.decode()))
        return Resp()

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)

    sd.send("loud")
    assert "disable_notification" not in bodies[-1]

    sd.send("quiet", silent=True)
    assert bodies[-1]["disable_notification"] is True


def test_heartbeat_is_silent_and_replaces_itself(env, monkeypatch, tmp_path):
    """Send-on-change made silence ambiguous: no message meant either nothing
    happened or the system died. The heartbeat resolves that."""
    from sigbot.config import Settings
    from sigbot.shadow import ShadowLedger

    import sigbot.runner as runner

    monkeypatch.chdir(tmp_path)
    led = ShadowLedger(str(tmp_path / "s.db"))
    for i in range(5):
        pid = led.record("daily", "X", "BUY", 0.6, 0.02, 100.0, horizon_hours=-1)
        if i < 3:
            led.resolve(pid, 103.0, bar_open=100.0, bar_high=103.5, bar_low=99.0)
    monkeypatch.setattr(runner, "SETTINGS", Settings(shadow_db=str(tmp_path / "s.db")))

    calls = []

    class Resp:
        def __init__(self, n):
            self.n = n

        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": self.n}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        if "deleteMessage" in url:
            calls.append(("delete", url))
            return Resp(0)
        payload = json.loads(req.data.decode())
        calls.append(("send", payload))
        return Resp(len(calls) + 100)

    monkeypatch.setattr(sd.urllib.request, "urlopen", fake)

    runner._send_heartbeat("Nothing changed.")
    first = [c for c in calls if c[0] == "send"][0][1]
    assert first["disable_notification"] is True, "a heartbeat must not buzz"
    assert "5 predictions made, 3 checked" in first["text"], (
        "the heartbeat must carry real numbers, or it proves only that a "
        "message can be sent")

    runner._send_heartbeat("Still nothing.")
    assert any(c[0] == "delete" for c in calls), (
        "48 heartbeats a day must not pile up in the chat")


def test_a_heartbeat_failure_is_recorded_not_raised(env, monkeypatch, tmp_path):
    import sigbot.runner as runner

    monkeypatch.chdir(tmp_path)

    def boom(*a, **k):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(sd.urllib.request, "urlopen", boom)
    runner._send_heartbeat("test")          # must not raise


# ------------------------------------------------------- the day summary

def _summary_setup(tmp_path):
    from sigbot.config import POOL, Settings
    from sigbot.shadow import ShadowLedger
    from sigbot.watchlist import Watchlist
    from tests.conftest import write_records

    settings = Settings(shadow_db=str(tmp_path / "s.db"),
                        watchlist_db=str(tmp_path / "w.db"))
    write_records(ShadowLedger(settings.shadow_db), "daily", "NVDA", 9, 0.55)
    Watchlist(settings.watchlist_db).seed(POOL)
    return settings


class _Capture:
    def __init__(self):
        self.msgs = []

    def send(self, text):
        self.msgs.append(text)


def test_day_summary_waits_for_the_last_close(tmp_path, monkeypatch):
    """Sending mid-session would report half a day as if it were the whole one."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sigbot.runner import run_day_summary

    monkeypatch.chdir(tmp_path)
    settings = _summary_setup(tmp_path)
    ist = ZoneInfo("Asia/Kolkata")

    cap = _Capture()
    run_day_summary(settings, cap, now=datetime(2026, 8, 31, 12, tzinfo=ist))
    assert cap.msgs == [], "spoke while NSE was open"

    run_day_summary(settings, cap, now=datetime(2026, 9, 1, 7, tzinfo=ist))
    assert len(cap.msgs) == 1


def test_day_summary_speaks_once_a_day(tmp_path, monkeypatch):
    """It runs hourly. Without the marker it would send once an hour all night."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from sigbot.runner import run_day_summary

    monkeypatch.chdir(tmp_path)
    settings = _summary_setup(tmp_path)
    when = datetime(2026, 9, 1, 7, tzinfo=ZoneInfo("Asia/Kolkata"))

    cap = _Capture()
    for hours in (0, 1, 2):
        run_day_summary(settings, cap, now=when + timedelta(hours=hours))
    assert len(cap.msgs) == 1, f"sent {len(cap.msgs)} times in one evening"


def test_day_summary_reports_the_record_and_admits_the_sample_is_tiny(tmp_path,
                                                                     monkeypatch):
    """Uses the real clock with the markets forced shut, rather than a fixed
    date. A hardcoded date drifts out of the 24-hour window as the real day
    advances, so this failed depending on the hour it was run — which is the
    kind of flake that teaches you to re-run instead of read."""
    from datetime import datetime, timezone

    import sigbot.runner as runner_module

    monkeypatch.chdir(tmp_path)
    settings = _summary_setup(tmp_path)
    # Market gating has its own tests; this one is about the ledger.
    monkeypatch.setattr(runner_module, "_markets_shut", lambda when: True,
                        raising=False)
    cap = _Capture()
    run_day_summary = runner_module.run_day_summary
    run_day_summary(settings, cap, now=datetime.now(timezone.utc))

    text = cap.msgs[0]
    assert "came due" in text and "were right" in text
    assert "worst case" in text
    assert "far too few to mean anything" in text, (
        "a one-day hit rate presented without that caveat invites reading it "
        "as performance")
    assert "Board:" in text and "All time:" in text


def test_day_summary_survives_an_unreadable_ledger(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sigbot.config import Settings
    from sigbot.runner import run_day_summary

    monkeypatch.chdir(tmp_path)
    broken = Settings(shadow_db="/nonexistent/dir/s.db",
                      watchlist_db="/nonexistent/dir/w.db")
    cap = _Capture()
    run_day_summary(broken, cap,
                    now=datetime(2026, 9, 1, 7, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert cap.msgs and "could not be read" in cap.msgs[0]
