"""Session idle TTL drops stale buffers."""

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "edge"))

from ttl import TTL_SECONDS, expire, touch  # noqa: E402


def test_idle_session_is_dropped():
    last = {}
    sessions = {"a": [{"event_type": "keydown"}]}
    score = {"a": 1.2}
    touch(last, "a", 0.0)
    dropped = expire(TTL_SECONDS + 1, last, [sessions, score])
    assert dropped == ["a"]
    assert sessions == {}
    assert score == {}
    assert last == {}


def test_fresh_session_is_kept():
    last = {}
    sessions = {"a": [1]}
    touch(last, "a", 100.0)
    dropped = expire(100.0 + 10, last, [sessions], ttl=30)
    assert dropped == []
    assert "a" in sessions


# ── through the real addon hook ────────────────────────────────

class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Request:
    def __init__(self, path, body=b"", method="POST", headers=None):
        self.path = path
        self.raw_content = body
        self.method = method
        self.host = "site.example"
        self.headers = _Headers(headers or {})


class _Flow:
    def __init__(self, request):
        self.request = request
        self.client_conn = type("Conn", (), {"peername": ("127.0.0.1", 54321)})()
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


def _typed(word, start=0.0):
    events = []
    t = start
    for i, ch in enumerate(word):
        events.append({"event_type": "keydown", "seq": i, "key": ch,
                       "is_modifier": False, "is_paste": False,
                       "is_trusted": True, "timestamp": t})
        events.append({"event_type": "keyup", "seq": i, "key": ch,
                       "is_modifier": False, "is_paste": False,
                       "is_trusted": True, "timestamp": t + 90.0})
        t += 150.0
    return events


def _telemetry(events, cookie="__cadence_sid=ttl1"):
    body = json.dumps({"events": events}).encode()
    return _Flow(_Request("/__cadence/telemetry", body, headers={"cookie": cookie}))


def _form_post(cookie="__cadence_sid=ttl1"):
    return _Flow(_Request(
        "/comment", b"message=hello",
        headers={"cookie": cookie,
                 "content-type": "application/x-www-form-urlencoded"},
    ))


def test_empty_heartbeats_do_not_keep_a_session_alive(monkeypatch):
    """The SDK interval beacon with events: [] is not activity. If it
    touched last_seen, any open tab would keep a stolen sid's keystroke
    buffer justifying POSTs forever — the exact threat TTL closes."""
    import addon

    for store in (addon.sessions, addon.score, addon.decisions,
                  addon.last_flags, addon.blocks, addon.last_seen,
                  addon.caep_emitted):
        store.clear()
    _fake_mitmproxy(monkeypatch)
    clock = {"now": 1_000.0}
    monkeypatch.setattr(addon, "time", types.SimpleNamespace(time=lambda: clock["now"]))

    addon.addons[0].request(_telemetry(_typed("hello")))
    justified = _form_post()
    addon.addons[0].request(justified)
    assert justified.response is None  # typed text: forwarded

    # Half a day of empty heartbeats, well past the TTL.
    while clock["now"] < 1_000.0 + TTL_SECONDS * 2:
        clock["now"] += 0.5
        addon.addons[0].request(_telemetry([]))

    stale = _form_post()
    addon.addons[0].request(stale)
    assert "ttl1" not in addon.sessions  # buffer expired despite beacons
    assert stale.response is not None
    assert stale.response.status_code == 403
