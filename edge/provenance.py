"""Provenance rules for form POSTs, as pure functions. No mitmproxy import.

A form POST claiming human text is only trustworthy if the proxy watched
that text being typed. The rules here answer three questions:

  * which session does a request belong to?  -> session_key()
  * does a POST body carry human text?        -> post_has_text()
  * is a POST justified by buffered input?    -> post_is_justified()

The policy in one sentence: a text-bearing form POST from a session with
zero keystrokes is not human provenance, and the proxy says so with a 403.

Session identity comes from a proxy-set cookie (__cadence_sid). The TCP
peer address is a fallback only: keep-alive and HTTP/2 merge or split
tabs in ways a peer address does not mean "user session".
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs

SESSION_COOKIE = "__cadence_sid"

# A POST with more than this many total keystrokes buffered is truncated at
# the head: recent typing is what justifies a form submission, and an
# unbounded buffer was the review's standing complaint. Counted per session.
MAX_EVENTS_PER_SESSION = 10_000

# Form fields that commonly carry human text. Passwords are excluded on
# purpose: managers and browsers type them, and a login form must not 403
# a human because their password was auto-filled.
TEXT_FIELDS = (
    "message",
    "body",
    "comment",
    "content",
    "text",
    "query",
    "q",
    "search",
    "description",
    "title",
    "subject",
    "answer",
    "reply",
    "note",
    "bio",
    "about",
    "name",
)

# What counts as "text" inside a matched field: at least one letter (any
# script), not just digits/punctuation. "123" is OTP-like; "hello" is text.
# [^\W\d_] is "word character that is not a digit or underscore" — i.e. a
# letter — and works across scripts under Python's default unicode mode
# (re has no \p{L}).
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def session_key(cookie_header: str | None, fallback: str) -> str:
    """The __cadence_sid cookie value, or the connection fallback."""
    if cookie_header:
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and value:
                return value
    return fallback


def new_session_id(seed: int) -> str:
    """A fresh opaque session id from a caller-supplied entropy source."""
    return f"{seed:016x}"


def post_has_text(body: bytes, content_type: str | None) -> bool:
    """True if a form body carries human text in a text-bearing field.

    JSON and other non-form bodies are out of scope: they return False,
    which means "not provenance-checked", never blocked.
    """
    if not body:
        return False
    ct = (content_type or "").lower()
    if "application/x-www-form-urlencoded" not in ct:
        return False
    try:
        fields = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    except ValueError:
        return False
    for name in TEXT_FIELDS:
        for value in fields.get(name, []):
            if _HAS_LETTER.search(value):
                return True
    return False


def count_keystrokes(events: list[dict]) -> int:
    """Character-producing keydowns in a buffer — the input that justifies text."""
    return sum(
        1
        for e in events
        if e.get("event_type") == "keydown"
        and not e.get("is_modifier")
        and not e.get("is_paste")
    )


def post_is_justified(body: bytes, content_type: str | None, events: list[dict]) -> bool:
    """False only when the POST carries text and the session typed nothing."""
    if not post_has_text(body, content_type):
        return True
    return count_keystrokes(events) > 0


def cap_session(events: list[dict], limit: int = MAX_EVENTS_PER_SESSION) -> list[dict]:
    """Keep the most recent `limit` events; drop the stale head."""
    if len(events) <= limit:
        return events
    return events[-limit:]
