"""Get signals onto your phone without an app.

You asked from the first message for a bot that messages you. That does not need
an App Store listing, a Mac, or a build toolchain — it needs an outbound HTTP
POST, which `messenger.WebhookMessenger` already does.

Telegram is the shortest path: no developer account, no review, no yearly fee,
and it works on iPhone, Android and desktop at once. Setup is two steps and
about five minutes.

    python -m sigbot.setup_delivery --telegram

Run it and it prints the exact commands, then verifies delivery end to end.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

TELEGRAM_STEPS = """
TELEGRAM SETUP — about five minutes, no account beyond Telegram itself

1. In Telegram, search for @BotFather and send:  /newbot
   Answer its two questions. It replies with a token that looks like
   1234567890:AAH_long_random_string, and with a link to your new bot.

2. Put the token in your shell. Do not paste it into a browser:

   export TELEGRAM_TOKEN="1234567890:AAH..."

   A token is the only thing needed to control the bot — send as it, read
   everything sent to it. In a browser address bar it ends up in history, in
   sync, and in any screenshot of the window.

3. Open YOUR bot, not BotFather. Use the t.me link BotFather just gave you,
   or search its @username. Press START, then send it anything.

   This is the step people miss. Messaging BotFather does nothing: it is a
   different account, and your bot never sees it.

4. Let this find your chat id:

   python -m sigbot.setup_delivery --chatid

5. Follow what it prints, then:

   python -m sigbot.setup_delivery --test

ONE THING TO EXPECT: your bot will never reply to you. It has no code behind
it. In this system it is a one-way pipe your Mac pushes messages through.
Silence after you message it is normal.
"""


def telegram_url() -> str:
    """Build the webhook URL WebhookMessenger expects, from the environment."""
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise RuntimeError(
            "TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must both be set. "
            "Run `python -m sigbot.setup_delivery --telegram` for the steps."
        )
    if ":" not in token:
        raise RuntimeError("that token does not look right — BotFather tokens contain a colon")
    q = urllib.parse.urlencode({"chat_id": chat})
    return f"https://api.telegram.org/bot{token}/sendMessage?{q}"


def send(text: str, url: str | None = None, timeout: float = 10.0,
         silent: bool = False) -> dict:
    """POST one message. Raises with the provider's own error text on failure.

    `silent` delivers without a notification. A heartbeat every half hour needs
    to be visible in the chat and must not buzz the phone, or it becomes the
    thing you mute — and muting the channel takes the real alerts with it.
    """
    url = url or telegram_url()
    payload: dict = {"text": text}
    if silent:
        payload["disable_notification"] = True
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(diagnose(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"could not reach Telegram: {exc.reason}. Check the machine has internet "
            "and that no proxy or firewall is blocking outbound HTTPS."
        ) from exc


def send_document(path: str, caption: str = "", timeout: float = 60.0) -> dict:
    """Upload a file to the Telegram chat.

    This is what removes the AirDrop step. The report arrives on the phone by
    itself; tapping it opens the whole thing in Safari. No hosting, no cable,
    no same-Wi-Fi requirement.

    Multipart is assembled by hand rather than pulling in `requests`, which
    would be a dependency added for one function.
    """
    import mimetypes
    import uuid

    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise RuntimeError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must both be set")

    file = os.fspath(path)
    data = open(file, "rb").read()
    name = os.path.basename(file)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    boundary = uuid.uuid4().hex

    def part(field: str, value: str) -> bytes:
        return (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{field}"\r\n\r\n{value}\r\n').encode()

    body = part("chat_id", chat)
    if caption:
        body += part("caption", caption[:1000])
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
             f'filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
    body += data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            diagnose(exc.code, exc.read().decode("utf-8", "replace")[:200])) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach Telegram: {exc.reason}") from exc


def send_file(path: str | os.PathLike, caption: str = "", timeout: float = 60.0) -> dict:
    """Push a file to your phone through the bot you already have.

    Removes the AirDrop step: the report arrives in the same chat as the alerts,
    and tapping it opens in Safari. A snapshot you have to remember to transfer
    is a snapshot you stop transferring.
    """
    import mimetypes
    import uuid

    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise RuntimeError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must both be set")

    path = os.fspath(path)
    name = os.path.basename(path)
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) > 50 * 1024 * 1024:
        raise RuntimeError(f"{name} is {len(blob) / 1e6:.0f} MB; Telegram caps files at 50 MB")

    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    parts: list[bytes] = []
    for field, value in (("chat_id", chat), ("caption", caption)):
        if value:
            parts += [f"--{boundary}\r\n".encode(),
                      f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode(),
                      value.encode("utf-8"), b"\r\n"]
    parts += [f"--{boundary}\r\n".encode(),
              f'Content-Disposition: form-data; name="document"; filename="{name}"\r\n'.encode(),
              f"Content-Type: {ctype}\r\n\r\n".encode(), blob, b"\r\n",
              f"--{boundary}--\r\n".encode()]
    body = b"".join(parts)

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            diagnose(exc.code, exc.read().decode("utf-8", "replace")[:200])) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach Telegram: {exc.reason}") from exc


LAST_REPORT_FILE = ".last_report"


def _delete_message(token: str, chat: str, message_id: int) -> bool:
    """Remove a message the bot sent. Telegram allows this for 48 hours."""
    url = (f"https://api.telegram.org/bot{token}/deleteMessage"
           f"?chat_id={urllib.parse.quote(str(chat))}&message_id={message_id}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("ok"))
    except Exception:  # handled: returns False, and the caller reports it
        return False


def send_report(path: str | os.PathLike, caption: str = "",
                state_path: str | os.PathLike = LAST_REPORT_FILE) -> dict:
    """Send the report and remove the one it replaces.

    Keeps exactly one report in the chat, so what you open is always current.
    A file sitting in a chat is a frozen copy — it shows whatever was true when
    it was sent, forever, with nothing on screen saying so. Leaving several
    behind means the one you happen to tap may be hours out of date.

    Honest constraint: Telegram only lets a bot delete its own messages for 48
    hours. Past that the old report stays, and the caption is the only thing
    telling you which is which — so the timestamp goes in the caption.

    Deletion failure never blocks the send. An extra stale copy is worse than
    tidy, but no copy at all is worse than both.
    """
    state = Path(state_path)
    previous: int | None = None
    if state.exists():
        try:
            previous = int(state.read_text().strip())
        except ValueError:  # a corrupt marker is not worth failing a send over
            previous = None

    result = send_file(path, caption=caption)
    message_id = (result.get("result") or {}).get("message_id")

    if previous and previous != message_id:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if token and chat and not _delete_message(token, chat, previous):
            print(f"could not remove the previous report (message {previous}) — "
                  "it may be over 48 hours old, or already gone")

    if message_id:
        state.write_text(str(message_id))
    return result


LAST_HEARTBEAT_FILE = ".last_heartbeat"


def send_heartbeat(text: str, state_path=LAST_HEARTBEAT_FILE) -> dict:
    """A short, silent proof of life that replaces the one before it.

    Sent with notifications suppressed, so 48 a day do not buzz 48 times — it
    sits in the chat, and when you look you know whether the thing is running.
    Replacing the previous one means the chat holds exactly one heartbeat rather
    than a wall of them.

    Silence from this system is otherwise ambiguous: no message means either
    nothing changed or it broke, and nothing on screen tells you which.
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        raise RuntimeError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must both be set")

    state = Path(state_path)
    previous = None
    if state.exists():
        try:
            previous = int(state.read_text().strip())
        except ValueError:  # a corrupt marker must not stop a heartbeat
            previous = None

    url = (f"https://api.telegram.org/bot{token}/sendMessage"
           f"?chat_id={urllib.parse.quote(str(chat))}"
           f"&disable_notification=true"
           f"&text={urllib.parse.quote(text[:900])}")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            diagnose(exc.code, exc.read().decode("utf-8", "replace")[:200])) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach Telegram: {exc.reason}") from exc

    message_id = (result.get("result") or {}).get("message_id")
    if previous and previous != message_id:
        _delete_message(token, chat, previous)
    if message_id:
        state.write_text(str(message_id))
    return result


def diagnose(status: int, detail: str) -> str:
    """Turn a provider error into the specific thing to change."""
    hints = {
        401: "the token is wrong or was revoked — get a fresh one from @BotFather",
        400: ("usually a wrong chat id, or you have not messaged the bot yet. "
              "A bot cannot open a conversation with you first."),
        403: "you blocked the bot, or the chat id belongs to someone else",
        404: "the token is malformed — check for a missing character when pasting",
        429: "rate limited; wait a minute and retry",
    }
    return f"Telegram returned {status}: {hints.get(status, 'unexpected')}\n  {detail}"


def verify(url: str | None = None) -> bool:
    """Send a test message and report clearly whether it landed."""
    try:
        url = url or telegram_url()
    except RuntimeError as exc:
        print(f"NOT CONFIGURED\n  {exc}")
        return False

    print("sending a test message...")
    try:
        result = send(
            "Sigbot delivery test.\n\nIf you can read this, signals will arrive here. "
            "No app, no App Store, no Mac.",
            url,
        )
    except RuntimeError as exc:
        print(f"FAILED\n  {exc}")
        return False

    if not result.get("ok", True):
        print(f"FAILED\n  {result}")
        return False
    print("DELIVERED — check your phone.\n\nAdd to cron:\n"
          "  0 20 * * *  cd /path/to/sigbot && python -m sigbot.runner daily")
    return True


def find_chat_id(url_base: str | None = None) -> int:
    """Read the chat id from recent messages to the bot. Never prints the token.

    Replaces the browser step from the old instructions. Pasting the token into
    an address bar puts it in browser history, in sync across devices, and in
    any screenshot of that window — which is exactly how one got exposed.
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        print("NOT CONFIGURED\n  TELEGRAM_TOKEN is not set. Run:\n"
              '    export TELEGRAM_TOKEN="1234567890:AAH..."')
        return 1
    if ":" not in token:
        print("That token does not look right — BotFather tokens contain a colon.")
        return 1

    base = url_base or f"https://api.telegram.org/bot{token}"
    try:
        with urllib.request.urlopen(f"{base}/getUpdates", timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(diagnose(exc.code, exc.read().decode("utf-8", "replace")[:200]))
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach Telegram: {exc.reason}")
        return 1

    if not data.get("ok"):
        print(f"Telegram refused the request: {data.get('description', data)}")
        return 1

    chats: dict[int, str] = {}
    for upd in data.get("result", []):
        for key in ("message", "edited_message", "channel_post"):
            chat = (upd.get(key) or {}).get("chat")
            if chat and "id" in chat:
                name = chat.get("first_name") or chat.get("title") or "you"
                chats[chat["id"]] = name

    if not chats:
        print(NO_MESSAGES_YET)
        return 1

    for cid, name in chats.items():
        print(f"Found a chat with {name}.\n\nRun this, then the test:\n"
              f'    export TELEGRAM_CHAT_ID="{cid}"\n'
              "    python -m sigbot.setup_delivery --test")
    return 0


NO_MESSAGES_YET = """The token works, but the bot has received no messages.

Telegram returned: {"ok":true,"result":[]}

Almost always one of these:

  1. You messaged @BotFather instead of your own bot. BotFather is a separate
     account and your bot never sees those messages. Open the t.me link
     BotFather gave you, or search your bot's @username.

  2. You opened the chat but did not press START, or did not send anything.
     Press START, then send "hi".

  3. Something already collected the updates. Telegram hands each update out
     once. Send a fresh message and try again.

  4. A webhook is set on this bot, which makes getUpdates always return empty.
     Clear it with:  python -m sigbot.setup_delivery --clear-webhook

And to be clear: the bot will not reply. It has no code behind it. Silence
after you message it is expected — you are only giving it something to read."""


def clear_webhook(url_base: str | None = None) -> int:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        print("TELEGRAM_TOKEN is not set.")
        return 1
    base = url_base or f"https://api.telegram.org/bot{token}"
    try:
        with urllib.request.urlopen(f"{base}/deleteWebhook", timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"Could not clear the webhook: {type(exc).__name__}: {exc}")
        return 1
    print("Webhook cleared." if data.get("ok") else f"Telegram said: {data}")
    print("Now send your bot a message and run: python -m sigbot.setup_delivery --chatid")
    return 0


def main(argv: list[str]) -> int:
    if "--telegram" in argv:
        print(TELEGRAM_STEPS)
        return 0
    if "--chatid" in argv:
        return find_chat_id()
    if "--clear-webhook" in argv:
        return clear_webhook()
    if "--test" in argv:
        return 0 if verify() else 1
    print("usage: python -m sigbot.setup_delivery "
          "[--telegram | --chatid | --test | --clear-webhook]")
    print("  --telegram        print the setup steps")
    print("  --chatid          find your chat id without exposing the token")
    print("  --test            send a test message and report what happened")
    print("  --clear-webhook   fix an empty getUpdates caused by a webhook")
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
