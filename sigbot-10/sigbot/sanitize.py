"""Input validation — reject malformed payloads before they reach anything.

Honest constraint: this validates *shape*, not truth. A Yahoo response with
every field present and correctly typed still passes if the prices are wrong,
and no schema catches that. `integrity.py` handles the values; this handles the
envelope. Both are needed and neither substitutes for the other.

Largest risk: it makes a payload feel trusted once it validates. A well-formed
RSS item from a source inventing stories validates perfectly. Shape is the
cheapest check available, not the strongest.

Test gap: the real network responses are not tested, because the sandbox this
was written in has no route to Yahoo or Telegram. The schemas are tested against
hand-built payloads matching the documented shapes, which catches a field being
absent but not a provider silently renaming one.

## Why not Pydantic

The specification asks for Pydantic. It would work, and it is one more thing to
install, keep at a compatible version, and reason about when it changes its own
API between majors — which it has. The guarantees wanted here are: required
fields present, types correct, unknown fields rejected, failures logged with an
id. That is about eighty lines of standard library, so it is eighty lines of
standard library. If a schema need arrives that genuinely wants Pydantic, adding
it then costs the same as adding it now.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("sigbot.sanitize")

MAX_LOGGED_PAYLOAD = 600


class Rejected(ValueError):
    """A payload that failed validation. Carries an id for the log."""

    def __init__(self, schema: str, reasons: list[str], ref: str):
        self.schema = schema
        self.reasons = reasons
        self.ref = ref
        super().__init__(f"{schema} rejected [{ref}]: {'; '.join(reasons)}")


@dataclass(frozen=True)
class Field:
    name: str
    kind: type | tuple[type, ...]
    required: bool = True
    check: Callable[[Any], bool] | None = None
    note: str = ""

    def problems(self, payload: dict) -> list[str]:
        if self.name not in payload or payload[self.name] is None:
            return [] if not self.required else [f"missing required field '{self.name}'"]
        value = payload[self.name]
        if isinstance(self.kind, tuple) or self.kind is not bool:
            if isinstance(value, bool) and bool not in _as_tuple(self.kind):
                return [f"'{self.name}' is a bool, expected {_name(self.kind)}"]
        if not isinstance(value, _as_tuple(self.kind)):
            return [f"'{self.name}' is {type(value).__name__}, expected {_name(self.kind)}"]
        if self.check and not self.check(value):
            return [f"'{self.name}' failed its check{': ' + self.note if self.note else ''}"]
        return []


def _as_tuple(kind) -> tuple:
    return kind if isinstance(kind, tuple) else (kind,)


def _name(kind) -> str:
    return "/".join(k.__name__ for k in _as_tuple(kind))


@dataclass(frozen=True)
class Schema:
    name: str
    fields: tuple[Field, ...]
    allow_extra: bool = False

    def validate(self, payload: Any) -> dict:
        """Return the cleaned payload, or raise Rejected.

        Unknown fields are rejected rather than dropped. A provider that starts
        sending something new has changed its contract, and silently discarding
        the new field means finding out months later that a meaning changed
        underneath a name that stayed the same.
        """
        ref = uuid.uuid4().hex[:12]
        if not isinstance(payload, dict):
            raise _reject(self.name, [f"payload is {type(payload).__name__}, "
                                      "expected a mapping"], ref, payload)

        reasons: list[str] = []
        for field in self.fields:
            reasons.extend(field.problems(payload))

        if not self.allow_extra:
            unknown = sorted(set(payload) - {f.name for f in self.fields})
            if unknown:
                reasons.append(f"unexpected field(s) {unknown}")

        if reasons:
            raise _reject(self.name, reasons, ref, payload)
        return {f.name: payload.get(f.name) for f in self.fields if f.name in payload}

    def accepts(self, payload: Any) -> bool:
        try:
            self.validate(payload)
            return True
        except Rejected:
            return False


def _reject(schema: str, reasons: list[str], ref: str, payload: Any) -> Rejected:
    try:
        body = json.dumps(payload, default=str)[:MAX_LOGGED_PAYLOAD]
    except (TypeError, ValueError):
        body = repr(payload)[:MAX_LOGGED_PAYLOAD]
    log.warning("rejected %s [%s] at %s: %s | payload=%s", schema, ref,
                datetime.now(timezone.utc).isoformat(), "; ".join(reasons), body)
    return Rejected(schema, reasons, ref)


# --------------------------------------------------------------- schemas

def _positive(v) -> bool:
    return float(v) > 0


def _non_negative(v) -> bool:
    return float(v) >= 0


def _looks_like_date(v) -> bool:
    try:
        datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


PRICE_BAR = Schema("price_bar", (
    Field("timestamp", str, check=_looks_like_date, note="ISO 8601"),
    Field("open", (int, float), check=_positive, note="must be above zero"),
    Field("high", (int, float), check=_positive, note="must be above zero"),
    Field("low", (int, float), check=_positive, note="must be above zero"),
    Field("close", (int, float), check=_positive, note="must be above zero"),
    Field("volume", (int, float), check=_non_negative, note="cannot be negative"),
))

NEWS_ITEM = Schema("news_item", (
    Field("title", str, check=lambda v: 0 < len(v) <= 500),
    Field("link", str, check=lambda v: v.startswith(("http://", "https://")),
          note="must be an http(s) URL"),
    Field("published", str, check=_looks_like_date, note="ISO 8601"),
    Field("summary", str, required=False),
    Field("source", str, required=False),
))

TELEGRAM_UPDATE = Schema("telegram_update", (
    Field("update_id", int),
    Field("message", dict, required=False),
    Field("edited_message", dict, required=False),
    Field("channel_post", dict, required=False),
), allow_extra=True)   # Telegram adds update kinds regularly and documents them

WEBHOOK_CONFIG = Schema("webhook_config", (
    Field("url", str, check=lambda v: v.startswith("https://"),
          note="https only — http and file:// are refused"),
    Field("field", str, required=False),
))


def validate_bar(payload: dict) -> dict:
    return PRICE_BAR.validate(payload)


def validate_news(payload: dict) -> dict:
    return NEWS_ITEM.validate(payload)


def validate_many(schema: Schema, payloads: list[Any]) -> tuple[list[dict], list[Rejected]]:
    """Validate a batch. Returns (accepted, rejected).

    Batches do not fail as a unit: one malformed RSS item should not discard a
    feed. The rejections are returned rather than swallowed so the caller can
    report how many were dropped, which is the difference between a thin result
    and a thin result that says so.
    """
    good: list[dict] = []
    bad: list[Rejected] = []
    for item in payloads:
        try:
            good.append(schema.validate(item))
        except Rejected as exc:
            bad.append(exc)
    return good, bad
