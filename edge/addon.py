"""mitmproxy addon: inject cadence-sdk.js into HTML responses, receive its telemetry.

Run via `cadence proxy`, or directly:

    mitmdump -s edge/addon.py
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

# edge/ is not an installed package; put it on sys.path so the sibling
# modules import regardless of where mitmproxy was launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inject import inject, is_html  # noqa: E402
from provenance import (  # noqa: E402
    SESSION_COOKIE,
    cap_session,
    new_session_id,
    post_is_justified,
    session_key,
)

EDGE_DIR = Path(__file__).resolve().parent
SDK_PATH = EDGE_DIR / "cadence-sdk.js"
SDK_SOURCE = SDK_PATH.read_text(encoding="utf-8")

TELEMETRY_PATH = "/__cadence/telemetry"

# session_key -> list of event dicts, in arrival order. Module-level so tests
# (and a future consumer) can inspect what the proxy has buffered. The key is
# the proxy-set __cadence_sid cookie when present, the TCP peer as fallback.
# Capped per session (head dropped) by cap_session on every append.
sessions: dict[str, list[dict]] = {}

_session_counter = itertools.count(1)


def _client_fallback(flow) -> str:
    """Connection fallback for the session key: request host + client address."""
    try:
        host = flow.request.host
    except AttributeError:
        host = "unknown"
    try:
        addr = flow.client_conn.peername if flow.client_conn is not None else None
    except AttributeError:
        addr = None
    return f"{host}|{addr}"


def _flow_session_key(flow) -> str:
    """Cookie first, connection fallback second — same rule on request and response."""
    try:
        cookie = flow.request.headers.get("cookie")
    except AttributeError:
        cookie = None
    return session_key(cookie, _client_fallback(flow))


class CadenceAddon:
    def request(self, flow):
        """Two responsibilities, in order: telemetry sink, provenance gate."""
        path = flow.request.path.split("?")[0]
        if path == TELEMETRY_PATH:
            self._swallow_telemetry(flow)
            return
        self._enforce_provenance(flow)

    def _swallow_telemetry(self, flow):
        """Buffer telemetry under the session key; never forward it upstream.

        Any method hitting the exact path is swallowed, not just POST — the
        path belongs to the proxy, so nothing on it should ever reach the
        upstream server regardless of verb.
        """
        events: list[dict] = []
        if flow.request.raw_content:
            try:
                payload = json.loads(flow.request.raw_content)
                maybe = payload.get("events") or []
                # list(1) raises TypeError, and that would error the flow
                # before the 204 below — turning a garbage payload into a
                # proxy-visible error instead of a swallow.
                if isinstance(maybe, list):
                    events = maybe
            except (ValueError, AttributeError):
                events = []
        key = _flow_session_key(flow)
        buffered = sessions.setdefault(key, [])
        buffered.extend(events)
        sessions[key] = cap_session(buffered)
        # A response set in the request hook short-circuits the proxy:
        # mitmproxy answers locally and nothing is forwarded upstream.
        from mitmproxy import http

        flow.response = http.Response.make(204, b"", {"Content-Type": "text/plain"})

    def _enforce_provenance(self, flow):
        """403 a text-bearing form POST from a session that typed nothing.

        The block is local: the request never reaches the upstream server.
        Fail-open by construction for anything the rules do not classify as
        text (JSON, multipart, unmatched field names, passwords).
        """
        if (flow.request.method or "").upper() != "POST":
            return
        body = flow.request.raw_content or b""
        content_type = flow.request.headers.get("content-type", "")
        events = sessions.get(_flow_session_key(flow), [])
        if post_is_justified(body, content_type, events):
            return
        from mitmproxy import http

        flow.response = http.Response.make(
            403,
            b"cadence: form submission without recorded keystrokes for this session.\n",
            {"Content-Type": "text/plain"},
        )

    def response(self, flow):
        response = flow.response
        if response is None:
            return
        if not is_html(response.headers.get("content-type", "")):
            return
        body = response.content or b""
        new = inject(body, SDK_SOURCE)
        # First HTML response on the connection seeds the session cookie so
        # telemetry and POSTs from this browser share one key even across
        # keep-alive reconnects or HTTP/2 stream splits.
        sid = new_session_id(next(_session_counter))
        set_cookie = f"{SESSION_COOKIE}={sid}; Path=/; SameSite=Lax"
        response.headers["Set-Cookie"] = set_cookie
        if new != body:
            response.content = new
            if "Content-Length" in response.headers:
                del response.headers["Content-Length"]


addons = [CadenceAddon()]
