"""
Step-up tests: a session whose fusion score crosses the Wald upper bound
gets 401 + WWW-Authenticate (RFC 9470), answered locally by the proxy.

The fake flows feed synthetic telemetry through the real addon request
hook; no mitmdump is started.
"""

import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from fusion import bounds  # noqa: E402

FORM = "application/x-www-form-urlencoded"


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


def _load_addon():
    import addon  # noqa: E402
    return addon


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


def _telemetry(events, cookie="__cadence_sid=s1"):
    body = json.dumps({"events": events}).encode()
    flow = _Flow(_Request("/__cadence/telemetry", body, headers={"cookie": cookie}))
    return flow


def _page_request(cookie="__cadence_sid=s1"):
    return _Flow(_Request("/anything", b"", method="GET", headers={"cookie": cookie}))


def _burst(n, gap, dwell, start=0.0, seq_offset=0):
    """A constant-timing burst — machine-like on its own."""
    events = []
    t = start
    for i in range(n):
        events.append({"event_type": "keydown", "seq": seq_offset + i, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t})
        events.append({"event_type": "keyup", "seq": seq_offset + i, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t + dwell})
        t += gap
    return events


def _attack_session():
    """A realistic attack in two telemetry rounds: a machine-like burst,
    then a DIFFERENT machine (faster, snappier) takes over the session.

    Round 1 alone: automation fires, drift sees one driver (no change).
    After round 2: automation still fires on the whole stream is not
    required — the walk already holds round 1's evidence; drift now sees
    two drivers. Accumulated, they cross the step-up bound. This mirrors
    reality: evidence arrives in rounds, not all at once."""
    first = _burst(30, 100.0, 80.0)
    offset = max(e["timestamp"] for e in first) + 600.0
    second = _burst(30, 70.0, 50.0, start=offset, seq_offset=100)
    return first, second


def _human_stream(n=60, seed=42, start=0.0):
    import random
    rng = random.Random(seed)
    events = []
    t = start
    for i in range(n):
        events.append({"event_type": "keydown", "seq": i, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t})
        events.append({"event_type": "keyup", "seq": i, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t + rng.uniform(60, 120)})
        t += rng.uniform(60, 180)
        if rng.random() < 0.08:
            t += rng.uniform(300, 900)
    return events


def test_machine_session_gets_401_with_challenge(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    r1, r2 = _attack_session()
    addon.addons[0].request(_telemetry(r1))
    addon.addons[0].request(_telemetry(r2))
    flow = _page_request()
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 401
    challenge = flow.response.headers.get("WWW-Authenticate")
    # RFC 9470: Bearer challenge, error=insufficient_user_authentication,
    # acr_values naming the required assurance level.
    assert challenge and challenge.startswith("Bearer")
    assert 'error="insufficient_user_authentication"' in challenge
    assert "acr_values=" in challenge


def test_human_session_is_untouched(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    addon.addons[0].request(_telemetry(_human_stream()))
    flow = _page_request()
    addon.addons[0].request(flow)

    assert flow.response is None  # forwarded; no challenge


def test_step_up_is_sticky_for_the_session(monkeypatch):
    """Once the walk says step-up, later requests are still challenged —
    evidence does not vanish; only a 'clean' decision clears it."""
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    r1, r2 = _attack_session()
    addon.addons[0].request(_telemetry(r1))
    addon.addons[0].request(_telemetry(r2))
    for _ in range(3):
        flow = _page_request()
        addon.addons[0].request(flow)
        assert flow.response is not None
        assert flow.response.status_code == 401


def test_step_up_survives_a_continue_round(monkeypatch):
    """A later round landing on 'continue' must NOT lift the 401: only a
    terminal clean decision clears it. The evidence that crossed the bound
    is still in the sum."""
    import random
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    r1, r2 = _attack_session()
    addon.addons[0].request(_telemetry(r1))
    addon.addons[0].request(_telemetry(r2))
    assert addon.decisions["s1"] == "step-up"

    # A short mixed/human burst: some honest evidence, nowhere near clean.
    rng = random.Random(99)
    humanish = []
    t = max(e["timestamp"] for e in r2) + 700.0
    for i in range(20):
        humanish.append({"event_type": "keydown", "seq": 500 + i, "is_modifier": False,
                         "is_paste": False, "key": "a", "timestamp": t})
        humanish.append({"event_type": "keyup", "seq": 500 + i, "is_modifier": False,
                         "is_paste": False, "key": "a", "timestamp": t + rng.uniform(60, 120)})
        t += rng.uniform(70, 200)
    addon.addons[0].request(_telemetry(humanish))
    assert addon.decisions["s1"] == "step-up"  # not lifted by continue

    flow = _page_request()
    addon.addons[0].request(flow)
    assert flow.response is not None
    assert flow.response.status_code == 401


def test_score_state_survives_across_requests(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    r1, r2 = _attack_session()
    addon.addons[0].request(_telemetry(r1))
    assert addon.decisions["s1"] == "step-up"  # round 1 alone: automation fires
    addon.addons[0].request(_telemetry(r2))
    assert addon.score["s1"] > bounds()[1]  # evidence survives round 2


def test_sessions_without_events_never_challenged(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _page_request()
    addon.addons[0].request(flow)
    assert flow.response is None


def test_provenance_403_still_fires_for_unjustified_text(monkeypatch):
    """The hard gate remains: typed-nothing POST with text still 403s, whether
    or not a step-up is in force."""
    addon = _load_addon()
    addon.sessions.clear()
    addon.score.clear()
    addon.decisions.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _Flow(
        _Request("/comment", b"message=hello+world",
                 headers={"cookie": "__cadence_sid=s9", "content-type": FORM})
    )
    addon.addons[0].request(flow)
    assert flow.response is not None
    assert flow.response.status_code == 403
