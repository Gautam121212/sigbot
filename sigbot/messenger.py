"""Message delivery and formatting.

Vendor-neutral by design: everything is a generic HTTP POST or a local sink.
Telegram, ntfy, Slack, Discord, Twilio and Pushover all accept a POST, so
switching provider is a config change, not a code change.

The formatter is the last line of defence against a dishonest message. It
will not print a probability the model has not earned, and it will not print
a magnitude the return distribution does not support.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .types import DailyForecast, NewsSignal


class ConsoleMessenger:
    def send(self, text: str) -> None:
        print(text, flush=True)


class FileMessenger:
    def __init__(self, path: str | Path = "outbox.log"):
        self.path = Path(path)

    def send(self, text: str) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n\n")


class WebhookMessenger:
    """POST {"text": ...} to any endpoint. Credentials come from the env only.

    `field` lets you match the provider's expected key without touching code:
      ntfy      -> raw body, set field=None
      Telegram  -> field="text" with chat_id in the URL query
      Slack     -> field="text"
    """

    def __init__(self, url_env: str = "SIGBOT_WEBHOOK_URL", field: str | None = "text",
                 timeout: float = 8.0, extra: dict | None = None):
        self.url = os.environ.get(url_env, "")
        if not self.url:
            raise RuntimeError(f"{url_env} is not set")
        # Only ever speak https. Without this, a mistyped or tampered variable
        # like file:///etc/passwd turns a delivery misconfiguration into a file
        # read, and urlopen would oblige.
        if not self.url.startswith("https://"):
            raise RuntimeError(
                f"{url_env} must start with https:// — refusing to send over "
                f"{self.url.split(':', 1)[0]}")
        self.field = field
        self.timeout = timeout
        self.extra = extra or {}

    def send(self, text: str) -> None:
        if self.field is None:
            body, ctype = text.encode("utf-8"), "text/plain; charset=utf-8"
        else:
            body = json.dumps({self.field: text, **self.extra}).encode("utf-8")
            ctype = "application/json"
        req = urllib.request.Request(self.url, data=body,
                                     headers={"Content-Type": ctype}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 300:
                    raise RuntimeError(f"webhook returned {resp.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"webhook delivery failed: {exc}") from exc


class TelegramMessenger:
    """Sends through the bot, splitting anything over Telegram's limit.

    A digest that runs past 4096 characters fails with a 400 and nothing
    arrives. Splitting is not tidy, but a message in two parts beats a message
    that silently did not send.
    """

    LIMIT = 3900          # the real cap is 4096; leave room for the part label

    # A message is split, never split indefinitely. Forty-two notifications
    # from one opportunity scan is not delivery, it is a denial of service on
    # your attention — and it is exactly what "split whatever you are given"
    # produces once the feed count goes from five to thirty-nine.
    MAX_PARTS = 3

    def __init__(self) -> None:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            raise RuntimeError("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are not set")
        self.token, self.chat = token, chat

    def _chunks(self, text: str) -> list[str]:
        if len(text) <= self.LIMIT:
            return [text]
        parts, current = [], ""
        for para in text.split("\n\n"):
            if len(current) + len(para) + 2 > self.LIMIT and current:
                parts.append(current)
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para
        if current:
            parts.append(current)
        if len(parts) > self.MAX_PARTS:
            kept = parts[: self.MAX_PARTS]
            dropped = len(parts) - self.MAX_PARTS
            kept[-1] += (f"\n\n[{dropped} more part(s) not sent. A message this "
                         "long means the sender had no limit of its own — the "
                         "full text is in the report and in outbox.log.]")
            parts = kept
        total = len(parts)
        return [f"({i}/{total})\n{p}" if total > 1 else p
                for i, p in enumerate(parts, 1)]

    def send(self, text: str) -> None:
        from .setup_delivery import send as _send

        for chunk in self._chunks(text):
            _send(chunk)


class MultiMessenger:
    """Deliver to several sinks; one failure must not silence the others."""

    def __init__(self, *sinks):
        self.sinks = list(sinks)

    def send(self, text: str) -> None:
        errors = []
        for sink in self.sinks:
            try:
                sink.send(text)
            except Exception as exc:  # noqa: BLE001 - delivery must be best-effort  # handled: collected and re-raised if every sink fails
                errors.append(f"{type(sink).__name__}: {exc}")
        if errors and len(errors) == len(self.sinks):
            raise RuntimeError("; ".join(errors))


# ------------------------------------------------------------------ formatting

def format_daily(f: DailyForecast, live_check: tuple[int, float, float] | None = None) -> str:
    arrow = {"BUY": "▲", "SELL": "▼", "HOLD": "•"}[f.side]
    lines = [
        f"{arrow} {f.asset.symbol} — {f.side}",
        f"24h expected move: {f.expected_move_pct:+.2%}  "
        f"(10–90% range {f.q10_pct:+.2%} to {f.q90_pct:+.2%})",
    ]
    if f.side == "HOLD":
        lines.append(f"Confidence: not enough to act (P(up) {f.p_up:.0%}, "
                     f"lower bound {f.p_up_lower:.0%})")
    else:
        shown = f.p_up_lower if f.side == "BUY" else 1.0 - f.p_up
        lines.append(f"Score: {shown:.0%}  ({f.n_calib_bin} calibration samples behind it)")
    for r in f.reasons[:3]:
        lines.append(f"  · {r}")
    for w in f.warnings[:3]:
        lines.append(f"  ! {w}")
    if live_check:
        n, hit, lo = live_check
        lines.append(f"Live track record: {n} resolved, {hit:.0%} hit rate "
                     f"(90% lower bound {lo:.0%})")
    lines.append(f"as of close {f.as_of:%Y-%m-%d}")
    return "\n".join(lines)


def format_candidate(c) -> str:
    """One-screen summary of a business candidate from the news scan.

    Shows the ceiling alongside the current score, because a candidate scoring 58
    that can reach 84 is worth an evening's work and one scoring 58 that tops out
    at 64 is not.
    """
    head = "*" if c.can_reach_plan else "-"
    lines = [
        f"{head} {c.opportunity.title}",
        f"  score {c.score:.0f}/100 now, up to {c.ceiling:.0f} if the unknowns resolve well",
        f"  gap: {c.gap_type.replace('_', ' ')}",
        f"  trigger: {c.opportunity.trigger[:110]}",
    ]
    if c.commodity:
        lines.append(f"  commodity thesis on {c.commodity} — run the carry test before "
                     "assuming storage pays")
    if c.needs_enrichment:
        lines.append("  you must answer: " +
                     ", ".join(k.replace("_", " ") for k in c.needs_enrichment))
    if not c.can_reach_plan:
        lines.append("  cannot reach the plan threshold even at best case — note and move on")
    return "\n".join(lines)


def format_news(s: NewsSignal) -> str:
    """One news signal, in the shape the Ideas cards use.

    The old format led with "Impact score: +0.42 on a -1..+1 scale" — the
    model's internal number, which means nothing to a reader. A card leads with
    what happened, what the model claims, and how much record stands behind
    that claim: the same three facts, in the order you need them.

    The colour is the claim, not the record, exactly as on the Ideas tab. A
    news signal is recorded and scored 24 hours later like any other forecast,
    so the record catches up. Until it does, the card says the claim is
    untested rather than dressing it as evidence.
    """
    strong = abs(s.raw_score) >= 0.60
    colour = "green" if strong else "amber"
    direction = "up" if s.side == "BUY" else "down"

    lines = ["NEWS — recorded and scored in 24 hours", "",
             f"{s.asset.symbol} {s.side} — the model reads today's coverage as "
             f"moving it {direction} ({colour})"]

    for article in s.articles[:2]:
        lines.append(f"    {article.title[:150]}")
        lines.append(f"      {article.source}, {article.published_at:%H:%M UTC}")

    if s.drivers:
        lines.append(f"    Because: {', '.join(s.drivers[:3])}")

    if s.magnitude_pct is not None:
        lines.append(f"    Expected move {s.magnitude_pct:+.2%} over 24 hours.")

    if s.validated and s.hit_rate_lower is not None:
        lines.append(f"    {s.n_observed} signals like this have been checked; "
                     f"worst case {s.hit_rate_lower:.0%} were right.")
    else:
        lines.append(f"    {s.n_observed} checked so far — too few to say "
                     "whether this model is right about anything, so this is a "
                     "thing to look at, not a probability.")
    return "\n".join(lines)
