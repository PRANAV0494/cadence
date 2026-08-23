"""mitmproxy addon: inject cadence-sdk.js into HTML responses, receive its telemetry.

Run via `cadence proxy`, or directly:

    mitmdump -s edge/addon.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# edge/ is not an installed package; put it on sys.path so the sibling
# inject module imports regardless of where mitmproxy was launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inject import inject, is_html  # noqa: E402

EDGE_DIR = Path(__file__).resolve().parent
SDK_PATH = EDGE_DIR / "cadence-sdk.js"
SDK_SOURCE = SDK_PATH.read_text(encoding="utf-8")

TELEMETRY_PATH = "/__cadence/telemetry"

# client_key -> list of event dicts, in arrival order. Module-level so tests
# (and a future consumer) can inspect what the proxy has buffered.
#
# UNBOUNDED: grows for the life of the process, one key per (host, client
# connection), and the boot script flushes every 5s without eviction. Fine
# for a local proxy run; the provenance work must replace this with a real
# session id (proxy-set cookie) and a cap — keep-alive and HTTP/2 already
# merge or split tabs in ways a TCP peer address does not mean "user session".
sessions: dict[str, list[dict]] = {}


def _client_key(flow) -> str:
    """Key events by the connection: request host + client address."""
    try:
        host = flow.request.host
    except AttributeError:
        host = "unknown"
    try:
        addr = flow.client_conn.peername if flow.client_conn is not None else None
    except AttributeError:
        addr = None
    return f"{host}|{addr}"


class CadenceAddon:
    def request(self, flow):
        """Swallow POSTs to the proxy-owned telemetry path; never forward them.

        Any method hitting the exact path is swallowed, not just POST — the
        path belongs to the proxy, so nothing on it should ever reach the
        upstream server regardless of verb.
        """
        if flow.request.path.split("?")[0] != TELEMETRY_PATH:
            return
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
        key = _client_key(flow)
        sessions.setdefault(key, []).extend(events)
        # A response set in the request hook short-circuits the proxy:
        # mitmproxy answers locally and nothing is forwarded upstream.
        from mitmproxy import http

        flow.response = http.Response.make(204, b"", {"Content-Type": "text/plain"})

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


addons = [CadenceAddon()]
