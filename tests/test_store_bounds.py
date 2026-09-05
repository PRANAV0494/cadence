"""Session-store bounds: table size and flush size are capped."""

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

KEYDOWN = {"event_type": "keydown", "is_modifier": False, "is_paste": False}


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


class _ClientConn:
    peername = ("127.0.0.1", 54321)


class _Flow:
    def __init__(self, request):
        self.request = request
        self.client_conn = _ClientConn()
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


def _telemetry_flow(cookie=None, events=None):
    headers = {"cookie": cookie} if cookie else {}
    body = json.dumps({"events": events or []}).encode()
    return _Flow(_Request("/__cadence/telemetry", body, headers=headers))


def _load_addon():
    import addon  # noqa: E402

    return addon


def test_flush_is_truncated(monkeypatch):
    from provenance import MAX_EVENTS_PER_SESSION  # noqa: E402

    addon = _load_addon()
    addon.sessions.clear()
    addon.last_seen.clear()
    _fake_mitmproxy(monkeypatch)

    burst = [dict(KEYDOWN, seq=i) for i in range(addon.MAX_EVENTS_PER_FLUSH + 100)]
    addon.addons[0].request(_telemetry_flow(cookie="__cadence_sid=c", events=burst))

    assert len(addon.sessions["c"]) <= MAX_EVENTS_PER_SESSION
    # most recent tail kept, oldest head dropped
    assert addon.sessions["c"][-1]["seq"] == addon.MAX_EVENTS_PER_FLUSH + 99


def test_new_session_evicts_oldest_when_full(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.last_seen.clear()
    addon.score.clear()
    addon.decisions.clear()
    addon.last_flags.clear()
    addon.blocks.clear()
    addon.caep_emitted.clear()
    _fake_mitmproxy(monkeypatch)

    monkeypatch.setattr(addon, "MAX_SESSIONS", 3)
    for i in range(3):
        addon.addons[0].request(
            _telemetry_flow(cookie=f"__cadence_sid=s{i}", events=[KEYDOWN])
        )
        addon.last_seen[f"s{i}"] = float(i)

    addon.addons[0].request(
        _telemetry_flow(cookie="__cadence_sid=new", events=[KEYDOWN])
    )

    assert "new" in addon.sessions
    assert len(addon.sessions) <= 3
    assert "s0" not in addon.sessions  # oldest idle evicted


def test_existing_session_never_evicts_itself(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.last_seen.clear()
    _fake_mitmproxy(monkeypatch)

    monkeypatch.setattr(addon, "MAX_SESSIONS", 1)
    addon.addons[0].request(_telemetry_flow(cookie="__cadence_sid=a", events=[KEYDOWN]))
    addon.addons[0].request(_telemetry_flow(cookie="__cadence_sid=a", events=[KEYDOWN]))

    assert "a" in addon.sessions


def _form_flow(port=54321, ip="127.0.0.1"):
    """A cookieless text-bearing form POST: takes the provenance block path."""
    flow = _Flow(
        _Request(
            "/submit",
            b"message=hello",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    )

    class _Conn:
        peername = (ip, port)

    flow.client_conn = _Conn()
    return flow


def _clear(addon):
    for store in (
        addon.sessions,
        addon.score,
        addon.decisions,
        addon.last_flags,
        addon.blocks,
        addon.caep_emitted,
        addon.last_seen,
    ):
        store.clear()


def test_block_path_is_bounded_and_expirable(monkeypatch):
    """The leak this PR missed.

    blocks and caep_emitted are written on the provenance/step-up block
    paths. Before the fix those paths called neither _evict_if_full nor
    touch(last_seen), and expire() iterates last_seen — so a cookieless
    scanner grew both stores forever with MAX_SESSIONS set to 10.
    """
    addon = _load_addon()
    _clear(addon)
    _fake_mitmproxy(monkeypatch)
    monkeypatch.setattr(addon, "MAX_SESSIONS", 10)

    # Distinct client IPs, so each POST really is a distinct session key.
    # Varying only the port would collapse to one key under the fallback fix
    # and the test would pass without the eviction fix doing anything.
    for i in range(200):
        addon.addons[0].request(_form_flow(ip=f"10.0.{i // 256}.{i % 256}"))

    assert addon.blocks, "expected the provenance gate to have blocked"
    assert len(addon.blocks) <= addon.MAX_SESSIONS, len(addon.blocks)
    assert len(addon.caep_emitted) <= addon.MAX_SESSIONS, len(addon.caep_emitted)
    # Every blocked key is in last_seen, so the TTL can actually reclaim it.
    assert set(addon.blocks) <= set(addon.last_seen)

    addon.addons[0].request(_form_flow(ip="10.9.9.9"))
    from ttl import expire  # noqa: E402

    expire(addon.last_seen[list(addon.last_seen)[0]] + 86_400,
           addon.last_seen, list(addon._STORES))
    assert addon.blocks == {}, "TTL did not reclaim blocked keys"
    assert addon.caep_emitted == {}


def test_fallback_key_ignores_ephemeral_port(monkeypatch):
    """One client, many connections, one key — not one key per TCP connection."""
    addon = _load_addon()
    _clear(addon)
    _fake_mitmproxy(monkeypatch)

    for port in range(50):
        addon.addons[0].request(_form_flow(port=port))

    assert len(addon.last_seen) == 1, addon.last_seen


def test_oversized_body_is_rejected_before_parsing(monkeypatch):
    """The byte bound, not the event cap, is what caps peak memory."""
    addon = _load_addon()
    _clear(addon)
    _fake_mitmproxy(monkeypatch)

    huge = b"x" * (addon.MAX_TELEMETRY_BODY_BYTES + 1)
    flow = _Flow(
        _Request("/__cadence/telemetry", huge, headers={"cookie": "__cadence_sid=big"})
    )

    def _boom(*a, **k):  # noqa: ANN001
        raise AssertionError("json.loads ran on an oversized body")

    monkeypatch.setattr(addon.json, "loads", _boom)
    addon.addons[0].request(flow)
    assert "big" not in addon.sessions
