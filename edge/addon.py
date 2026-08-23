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

from inject import csp_hashes, inject, is_html  # noqa: E402
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
SDK_HASHES = csp_hashes(SDK_SOURCE)

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


def _request_cookie(flow) -> str | None:
    try:
        return flow.request.headers.get("cookie")
    except AttributeError:
        return None


def _existing_sid(flow) -> str | None:
    """The sid the request already carries, or None."""
    sid = session_key(_request_cookie(flow), "")
    return sid or None


def _set_cookie_if_absent(response, flow) -> None:
    """Mint a session cookie only when the request did not already carry one.

    Rotating __cadence_sid on every HTML response was the first version's
    fatal bug: telemetry buffered under the old id, the next page minted a
    new one, and the form POST saw an empty buffer and 403'd a human.
    The cookie is minted once per browser session, here and on the telemetry
    204. Never overwrites the upstream's Set-Cookie (mitmproxy headers
    support multiple values; fakes in tests use .add when present).
    """
    if _existing_sid(flow) is not None:
        return
    sid = new_session_id(next(_session_counter))
    _add_set_cookie(response, sid)


def _add_set_cookie(response, sid: str) -> None:
    set_cookie = f"{SESSION_COOKIE}={sid}; Path=/; SameSite=Lax"
    add = getattr(response.headers, "add", None)
    if callable(add):
        add("Set-Cookie", set_cookie)
    else:
        if "Set-Cookie" not in response.headers:
            response.headers["Set-Cookie"] = set_cookie


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
        # Mint BEFORE buffering: if this beacon has no cookie yet (it can
        # beat the first HTML response), the buffer and the newly issued
        # cookie must share one id, or one browser becomes two sessions.
        existing = _existing_sid(flow)
        key = existing if existing is not None else new_session_id(next(_session_counter))
        buffered = sessions.setdefault(key, [])
        buffered.extend(events)
        sessions[key] = cap_session(buffered)
        # A response set in the request hook short-circuits the proxy:
        # mitmproxy answers locally and nothing is forwarded upstream.
        from mitmproxy import http

        flow.response = http.Response.make(
            204,
            b"",
            {"Content-Type": "text/plain"},
        )
        if existing is None:
            _add_set_cookie(flow.response, key)

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
        if new != body:
            response.content = new
            if "Content-Length" in response.headers:
                del response.headers["Content-Length"]
            self._allow_injected_scripts_in_csp(response)
        # Mint the session cookie only on first sight: telemetry and POSTs
        # from this browser then share one key even across keep-alive
        # reconnects or HTTP/2 stream splits. Never rotates an existing sid.
        _set_cookie_if_absent(response, flow)

    def _allow_injected_scripts_in_csp(self, response) -> None:
        """Append our script hashes to script-src so a strict CSP lets the
        injected SDK run. Without this, a page with Content-Security-Policy
        blocks the inline scripts, telemetry never starts, and provenance
        is blind. No CSP header → nothing to extend.

        Only script-src (or a default-src fallback) is touched, and only by
        appending tokens — never removing the page's own restrictions.
        """
        csp = response.headers.get("Content-Security-Policy")
        if not csp:
            return
        import re

        directives = re.split(r"\s*;\s*", csp)
        target = None
        for i, d in enumerate(directives):
            name = d.split(None, 1)[0].lower() if d.strip() else ""
            if name == "script-src":
                target = i
                break
            if name == "default-src" and target is None:
                target = i
        if target is None:
            # A policy with neither script-src nor default-src cannot govern
            # scripts; nothing to extend.
            return
        # CSP2+ deactivates 'unsafe-inline' on a directive the moment any
        # hash or nonce appears in it. If the governing directive already
        # allows inline scripts, appending our hashes would BREAK the page's
        # own inline scripts while adding nothing: they already permit ours.
        if "'unsafe-inline'" in directives[target]:
            return
        existing = directives[target]
        additions = [h for h in SDK_HASHES if h not in existing]
        if not additions:
            return
        directives[target] = existing.rstrip() + " " + " ".join(additions)
        response.headers["Content-Security-Policy"] = "; ".join(directives)


addons = [CadenceAddon()]
