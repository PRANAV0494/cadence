"""
Live console tests: the page is served on the proxy-owned path, the
snapshot reflects addon state, blocks are counted. No mitmdump, no real
WebSocket — the push helper's payload is tested directly.
"""

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from console import CONSOLE_PATH, CONSOLE_STATE_PATH, PAGE, snapshot  # noqa: E402


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Req:
    def __init__(self, path):
        self.path = path
        self.method = "GET"
        self.raw_content = b""
        self.host = "site.example"
        self.headers = _Headers({})
        self.headers["cookie"] = "__cadence_sid=live1"


class _Conn:
    peername = ("127.0.0.1", 7777)


class _Flow:
    def __init__(self, path):
        self.request = _Req(path)
        self.client_conn = _Conn()
        self.response = None


def _fake_mitmproxy(monkeypatch):
    class _Resp:
        def __init__(self, code, content, headers):
            self.status_code = code
            self.content = content
            self.headers = _Headers(dict(headers))

        @classmethod
        def make(cls, code, content, headers):
            return cls(code, content, headers)

    http_mod = types.ModuleType("mitmproxy.http")
    http_mod.Response = _Resp
    root_mod = types.ModuleType("mitmproxy")
    root_mod.http = http_mod
    monkeypatch.setitem(sys.modules, "mitmproxy", root_mod)
    monkeypatch.setitem(sys.modules, "mitmproxy.http", http_mod)


def _load_addon():
    import addon  # noqa: E402
    return addon


def test_console_page_is_served_locally(monkeypatch):
    addon = _load_addon()
    _fake_mitmproxy(monkeypatch)
    flow = _Flow(CONSOLE_PATH)
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 200
    body = flow.response.content.decode("utf-8")
    assert "cadence console" in body
    assert "fetch" in body
    assert CONSOLE_STATE_PATH in body  # state path substituted


def test_snapshot_reports_decision_flags_and_blocks():
    class _State:
        sessions = {"live1": [{"event_type": "keydown"}]}
        decisions = {"live1": "step-up"}
        score = {"live1": 4.2}
        last_flags = {"live1": {"automation": True, "drift": None, "provenance": None}}
        blocks = {"live1": 3}

    data = json.loads(snapshot(_State))
    (session,) = data["sessions"]
    assert session["decision"] == "step-up"
    assert session["score"] == 4.2
    assert session["flags"]["automation"] is True
    assert session["blocks"] == 3
    assert data["dropped"] == 3


def test_long_sids_are_masked():
    class _State:
        long_sid = "a" * 40
        sessions = {long_sid: []}
        decisions = {}
        score = {}
        last_flags = {}
        blocks = {}

    data = json.loads(snapshot(_State))
    (session,) = data["sessions"]
    assert len(session["sid"]) < 20
    assert session["sid"].startswith("a") and "..." in session["sid"]


def test_blocked_requests_increment_the_counter(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.blocks.clear()
    addon.decisions.clear()
    addon.score.clear()
    addon.last_flags.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _Flow("/comment")
    flow.request.method = "POST"
    flow.request.raw_content = b"message=hello+world"
    flow.request.headers["content-type"] = "application/x-www-form-urlencoded"
    flow.request.headers["cookie"] = "__cadence_sid=live1"
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 403
    assert addon.blocks.get("live1") == 1


def test_state_endpoint_returns_json(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear(); addon.blocks.clear()
    addon.decisions.clear(); addon.score.clear(); addon.last_flags.clear()
    _fake_mitmproxy(monkeypatch)

    addon.addons[0]._accumulate("live1", [])
    flow = _Flow(CONSOLE_STATE_PATH)
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 200
    data = json.loads(flow.response.content)
    assert "sessions" in data and "dropped" in data


def test_console_page_is_not_instrumented(monkeypatch):
    """The console is HTML served by the proxy itself - the response hook
    must not inject the SDK or mint a cookie on /__cadence/* paths."""
    addon = _load_addon()

    class _Resp:
        def __init__(self):
            self.content = b"<html><body></body></html>"
            from collections import OrderedDict
            self.headers = _Headers({"Content-Type": "text/html"})

    flow = _Flow(CONSOLE_PATH)
    flow.response = _Resp()
    addon.addons[0].response(flow)
    assert b'id="cadence-sdk"' not in flow.response.content
    assert flow.response.headers.get("Set-Cookie") is None


def test_page_contains_no_detectors():
    """Demo only: the console page ships no detection logic of its own."""
    import re

    assert not re.search(r"function (detect|isAutomated|drift)", PAGE)
