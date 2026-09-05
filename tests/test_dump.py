"""CADENCE_DUMP_DIR writes JSONL flushes; unset env writes nothing."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "edge"))

from dump import MAX_DUMP_EVENTS, append_flush, filename  # noqa: E402


def test_filename_strips_connection_fallback_punctuation():
    assert filename(r"127.0.0.1|(1, 2)") == "127.0.0.1_1_2.jsonl"


def test_append_flush_writes_eval_shaped_jsonl(tmp_path):
    events = [{"event_type": "keydown", "seq": 0, "key": "a", "timestamp": 1.0}]
    path = append_flush("abc", events, dest=tmp_path)
    assert path == tmp_path / "abc.jsonl"
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line == {"events": events}


def test_append_flush_noops_without_dest(monkeypatch, tmp_path):
    monkeypatch.delenv("CADENCE_DUMP_DIR", raising=False)
    assert append_flush("abc", [{"event_type": "keydown"}]) is None
    assert list(tmp_path.iterdir()) == []


def test_append_flush_truncates_to_recent_tail(tmp_path):
    events = [{"event_type": "keydown", "seq": i} for i in range(MAX_DUMP_EVENTS + 100)]
    path = append_flush("abc", events, dest=tmp_path)
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert len(line["events"]) == MAX_DUMP_EVENTS
    assert line["events"][-1]["seq"] == MAX_DUMP_EVENTS + 99


def test_bad_dump_dir_fails_open_in_telemetry(monkeypatch, tmp_path):
    """A file where the dump dir should be must not break the 204 ack."""
    import sys
    import types

    sys.path.insert(0, str(REPO / "edge"))
    import addon  # noqa: E402

    class _Headers(dict):
        def get(self, key, default=None):
            for k, v in self.items():
                if k.lower() == key.lower():
                    return v
            return default

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

    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("CADENCE_DUMP_DIR", str(blocker))

    addon.sessions.clear()
    addon.last_seen.clear()

    class _Request:
        path = "/__cadence/telemetry"
        raw_content = json.dumps(
            {"events": [{"event_type": "keydown", "key": "a"}]}
        ).encode()
        method = "POST"
        host = "site.example"
        headers = _Headers({})

    class _Flow:
        def __init__(self, request):
            self.request = request
            self.client_conn = None
            self.response = None

    flow = _Flow(_Request())
    addon.addons[0].request(flow)
    assert flow.response is not None
    assert flow.response.status_code == 204
