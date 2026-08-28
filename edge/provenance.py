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

from trusted import is_trusted

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
        and is_trusted(e)
    )


def typed_string(events: list[dict]) -> str:
    """Reconstruct what was actually typed: characters from character-producing
    keydowns, backspace pops the last character, modifiers and pastes skipped.

    This is the provenance claim the proxy can actually verify: the submitted
    text must be contained in this string.
    """
    chars: list[str] = []
    for e in events:
        if e.get("event_type") != "keydown":
            continue
        if e.get("is_paste"):
            continue
        if not is_trusted(e):
            continue
        # Backspace is recorded as key='Backspace' (multi-char) with
        # is_backspace set — test the flag before the single-char filter,
        # or every backspace is silently skipped.
        if e.get("is_backspace"):
            if chars:
                chars.pop()
            continue
        key = e.get("key")
        # Enter is is_modifier in the SDK (no character in the key name)
        # but a textarea still inserts a newline. Space is " " in Chrome
        # and "Spacebar" in older UAs.
        if key in ("Enter", "Return"):
            chars.append("\n")
            continue
        if key in (" ", "Space", "Spacebar"):
            chars.append(" ")
            continue
        if e.get("is_modifier"):
            continue
        if not isinstance(key, str) or len(key) != 1:
            continue
        chars.append(key)
    return "".join(chars)


def _urlencoded_fields(body: bytes) -> dict[str, str]:
    try:
        fields = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    except ValueError:
        return {}
    return {
        name: values[0]
        for name in TEXT_FIELDS
        for values in [fields.get(name, [])]
        if values
    }


def _json_fields(body: bytes) -> dict[str, str]:
    """Text-bearing top-level string fields of a JSON body.

    Nested objects are not traversed: the top level is where APIs put
    the human text this gate is about. Non-string values are skipped.
    Any parse failure fails open ({}).
    """
    import json as _json

    try:
        data = _json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        name: value
        for name, value in data.items()
        if name in TEXT_FIELDS and isinstance(value, str) and value
    }


def _multipart_fields(body: bytes, content_type: str | None) -> dict[str, str]:
    """Text parts of a multipart/form-data body, by part name.

    File parts fail open by design: an uploaded binary is never typed
    text, and filenames are chosen from menus as often as typed. Only a
    part whose name is text-bearing AND whose content looks textual is
    checked. Minimal boundary-split parsing, fail-open on malformed
    parts.
    """
    # RFC 2046: parameter names are case-insensitive; Boundary=B is legal.
    match = re.search(r'boundary="?([^";]+)"?', content_type or "", re.IGNORECASE)
    if not match:
        return {}
    boundary = match.group(1).encode()
    sep = b"\r\n"
    header_sep = b"\r\n\r\n"
    fields: dict[str, str] = {}
    for part in body.split(b"--" + boundary):
        # Parts arrive as: b"\r\n<headers>\r\n\r\n<value>". Strip ONLY the
        # exact leading/trailing CRLF — bytes.strip() would eat whitespace
        # inside the value itself, corrupting the text under check.
        if part.startswith(sep):
            part = part[len(sep):]
        part = part.rstrip(sep)
        if not part or part == b"--":
            continue
        header_blob, _, value_blob = part.partition(header_sep)
        if not value_blob:
            continue
        name_match = re.search(rb'name="([^"]+)"', header_blob)
        if not name_match:
            continue
        name = name_match.group(1).decode("utf-8", errors="replace")
        is_file = b"filename=" in header_blob
        ct_lines = [
            line for line in header_blob.split(sep)
            if line.lower().startswith(b"content-type:")
        ]
        declared = ct_lines[0].split(b":", 1)[1].strip().lower() if ct_lines else b""
        text_like = (
            not is_file
            and (b"text/" in declared or declared in (b"", b"text/plain"))
        )
        if name in TEXT_FIELDS and text_like:
            fields[name] = value_blob.decode("utf-8", errors="replace")
    return fields


def text_fields_in_body(body: bytes, content_type: str | None) -> dict[str, str]:
    """Name -> first value for text-bearing fields, across body formats.

    urlencoded, JSON (top-level string fields), and multipart text parts
    share the same substring rule downstream. Files, binaries, and
    anything unparseable contribute nothing: the gate fails open for
    what it cannot read as typed text.
    """
    if not body:
        return {}
    ct = (content_type or "").lower()
    if "application/x-www-form-urlencoded" in ct:
        return _urlencoded_fields(body)
    if "application/json" in ct:
        return _json_fields(body)
    if "multipart/form-data" in ct:
        return _multipart_fields(body, content_type)
    return {}


def post_is_justified(body: bytes, content_type: str | None, events: list[dict]) -> bool:
    """False only when a text field's value is not contained in the typed string.

    One stray keydown no longer justifies arbitrary text: the submitted value
    must be a substring of what the session actually typed. Empty typed plus
    a text field is unjustified. Non-form and non-text bodies pass.
    """
    fields = text_fields_in_body(body, content_type)
    if not fields:
        return True
    typed = _fold_newlines(typed_string(events))
    for value in fields.values():
        if _HAS_LETTER.search(value) and _fold_newlines(value) not in typed:
            return False
    return True


def _fold_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def cap_session(events: list[dict], limit: int = MAX_EVENTS_PER_SESSION) -> list[dict]:
    """Keep the most recent `limit` events; drop the stale head."""
    if len(events) <= limit:
        return events
    return events[-limit:]
