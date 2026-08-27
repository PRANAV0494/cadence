"""
Tests for the edge injector: pure-function injection plus the CLI surface.
No mitmdump is started anywhere in this file.
"""

import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from inject import already_injected, inject, is_html  # noqa: E402

SDK = (EDGE / "cadence-sdk.js").read_text(encoding="utf-8")

PAGE = b"<html><body><p>hi</p></body></html>"


# ── is_html ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "content_type, expected",
    [
        ("text/html", True),
        ("text/html; charset=utf-8", True),
        ("TEXT/HTML", True),
        ("application/json", False),
        (None, False),
        ("", False),
    ],
)
def test_is_html(content_type, expected):
    assert is_html(content_type) is expected


# ── inject ─────────────────────────────────────────────────────

def test_inject_adds_sdk_before_closing_body():
    result = inject(PAGE, SDK)
    assert b'id="cadence-sdk"' in result
    assert b"createRecorder" in result
    assert b"CadenceSDK" in result
    assert b"r.attach(document)" in result
    assert b"</body>" in result
    assert already_injected(result) is True


def test_inject_is_idempotent():
    first = inject(PAGE, SDK)
    assert inject(first, SDK) == first


def test_uppercase_body_tag_still_injects():
    result = inject(b"<html><body><p>hi</p></BODY></html>", SDK)
    assert already_injected(result) is True
    assert b"</BODY>" in result


def test_no_body_tag_returns_input_unchanged():
    page = b"<html><p>hi</p></html>"
    assert inject(page, SDK) is page


def test_already_injected_page_is_unchanged():
    page = b'<html><body><script id="cadence-sdk">x</script></body></html>'
    assert inject(page, SDK) is page


def test_sdk_source_appears_raw_not_escaped():
    result = inject(PAGE, SDK)
    assert "function createRecorder" in result.decode("utf-8")
    assert b"\\u" not in result


# ── CLI ────────────────────────────────────────────────────────

def test_boot_block_waits_for_telemetry_on_submit():
    from inject import BOOT_BLOCK

    assert 'addEventListener("submit"' in BOOT_BLOCK
    assert "preventDefault" in BOOT_BLOCK
    assert 'fetch("/__cadence/telemetry"' in BOOT_BLOCK
    assert "HTMLFormElement.prototype.submit" in BOOT_BLOCK
    assert "pending" in BOOT_BLOCK
    assert "setInterval(push, 500)" in BOOT_BLOCK


def test_addon_script_does_not_export_update():
    """mitmproxy calls module-level update() as an options hook with no
    args. fusion.update(llr, signals) must not sit on that name."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cadence_addon_hook_check", EDGE / "addon.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert not hasattr(mod, "update")


def test_cli_help_exits_zero_and_mentions_proxy(capsys):
    from cadence import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "proxy" in out


def test_cli_proxy_without_mitmdump_exits_2(monkeypatch, capsys):
    from cadence import cli

    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(SystemExit) as exc:
        cli.main(["proxy"])
    assert exc.value.code == 2
    assert "cadence[proxy]" in capsys.readouterr().err


# ── addon.response() with a duck-typed flow ────────────────────

class _Headers(dict):
    """Dict with case-insensitive-ish delete, like mitmproxy's headers."""

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Response:
    def __init__(self, content, content_type):
        self.content = content
        self.headers = _Headers({"Content-Type": content_type, "Content-Length": "999"})


class _Flow:
    def __init__(self, content, content_type):
        self.response = _Response(content, content_type)


def _load_addon():
    sys.path.insert(0, str(EDGE))
    import addon  # noqa: E402
    return addon


def test_addon_injects_into_html_flow():
    addon = _load_addon()
    flow = _Flow(b"<html><body><p>hi</p></body></html>", "text/html; charset=utf-8")
    addon.addons[0].response(flow)
    assert b'id="cadence-sdk"' in flow.response.content
    assert flow.response.headers.get("Content-Length") is None  # recalculated by the proxy


def test_addon_skips_non_html_flow():
    addon = _load_addon()
    original = b'{"a": 1}'
    flow = _Flow(original, "application/json")
    addon.addons[0].response(flow)
    assert flow.response.content is original


def test_addon_skips_flow_without_response():
    addon = _load_addon()

    class _NoResponse:
        response = None

    flow = _NoResponse()
    addon.addons[0].response(flow)  # must not raise


# ── telemetry: request() swallows and buffers ──────────────────

class _TelemetryRequest:
    def __init__(self, path, body):
        self.path = path
        self.raw_content = body
        self.method = "POST"
        self.host = "site.example"
        self.headers = _Headers({})


class _TelemetryFlow:
    def __init__(self, path, body):
        self.request = _TelemetryRequest(path, body)
        self.client_conn = type(
            "Conn", (), {"peername": ("127.0.0.1", 54321)}
        )()
        self.response = None


def _install_fake_mitmproxy(monkeypatch):
    """addon.request imports mitmproxy.http inside the hook; supply a stub."""
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


def test_telemetry_post_is_swallowed_and_buffered(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _install_fake_mitmproxy(monkeypatch)

    body = json.dumps(
        {"events": [{"event_type": "keydown", "seq": 0, "code": "KeyA"}]}
    ).encode()
    flow = _TelemetryFlow("/__cadence/telemetry", body)
    addon.addons[0].request(flow)

    # Answered locally with 204 — never forwarded upstream.
    assert flow.response is not None
    assert flow.response.status_code == 204
    # Buffered under the connection key.
    (key,) = addon.sessions.keys()
    assert addon.sessions[key][0]["code"] == "KeyA"


def test_query_string_still_hits_the_telemetry_path(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _install_fake_mitmproxy(monkeypatch)

    body = json.dumps({"events": [{"event_type": "keyup", "seq": 0}]}).encode()
    flow = _TelemetryFlow("/__cadence/telemetry?x=1", body)
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert len(list(addon.sessions.values())[0]) == 1


def test_malformed_telemetry_body_is_swallowed_not_crashed(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _install_fake_mitmproxy(monkeypatch)

    flow = _TelemetryFlow("/__cadence/telemetry", b"not json at all")
    addon.addons[0].request(flow)

    assert flow.response is not None  # still 204, still not forwarded
    assert all(v == [] for v in addon.sessions.values())


def test_non_list_events_is_swallowed_not_crashed(monkeypatch):
    """
    {"events": 1} parses as JSON; list(1) is TypeError. That raised before
    the 204 was set, erroring the flow instead of swallowing it.
    """
    addon = _load_addon()
    addon.sessions.clear()
    _install_fake_mitmproxy(monkeypatch)

    flow = _TelemetryFlow("/__cadence/telemetry", b'{"events": 1}')
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 204
    assert all(v == [] for v in addon.sessions.values())


def test_other_requests_are_untouched(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _install_fake_mitmproxy(monkeypatch)

    flow = _TelemetryFlow("/login", b"username=x")
    addon.addons[0].request(flow)

    assert flow.response is None  # forwarded normally, nothing answered locally
    assert addon.sessions == {}


def test_telemetry_events_survive_flush_boundaries_in_the_buffer(monkeypatch):
    """Two beacons from one browser accumulate under one key.

    A real browser echoes the minted __cadence_sid after the first 204;
    the fake flow does the same, or each cookie-less beacon would mint
    its own session.
    """
    addon = _load_addon()
    addon.sessions.clear()
    _install_fake_mitmproxy(monkeypatch)

    cookie = None
    for seq in (0, 1):
        body = json.dumps(
            {"events": [{"event_type": "keydown", "seq": seq, "code": "KeyA"}]}
        ).encode()
        flow = _TelemetryFlow("/__cadence/telemetry", body)
        if cookie:
            flow.request.headers["cookie"] = cookie
        addon.addons[0].request(flow)
        if flow.response is not None:
            minted = flow.response.headers.get("Set-Cookie")
            if minted and "__cadence_sid=" in minted:
                cookie = minted.split(";")[0]

    (key,) = addon.sessions.keys()
    assert [e["seq"] for e in addon.sessions[key]] == [0, 1]


# ── SDK drain/flush under Node ─────────────────────────────────

# These drive the real SDK in Node; without node on PATH they would fail
# hard instead of skipping like the contract tests in
# test_sdk_extractor_contract.py do.
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is required for SDK tests")


def _run_node(script_body: str) -> dict:
    script = (
        "const sdk = require(" + json.dumps(str(EDGE / "cadence-sdk.js")) + ");\n"
        "const { createRecorder, flush } = sdk;\n"
        "let now = 0; performance.now = () => now;\n"
        + script_body
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, f"node failed: {out.stderr}"
    return json.loads(out.stdout)


@node
def test_drain_hands_off_and_continues_seq():
    data = _run_node(
        """
        const r = createRecorder();
        r.onKeyDown({ code: 'KeyA', key: 'a', repeat: false, isTrusted: true });
        now += 85;
        r.onKeyUp({ code: 'KeyA', key: 'a', isTrusted: true });
        const first = r.drain();
        r.onKeyDown({ code: 'KeyB', key: 'b', repeat: false, isTrusted: true });
        now += 90;
        r.onKeyUp({ code: 'KeyB', key: 'b', isTrusted: true });
        const second = r.drain();
        const again = r.drain();
        process.stdout.write(JSON.stringify({ first, second, again }));
        """
    )
    # First flush: keydown seq 0 + keyup paired to 0.
    assert [e["seq"] for e in data["first"]] == [0, 0]
    # After a flush boundary, seq continues — pairing survives the boundary.
    assert [e["seq"] for e in data["second"]] == [1, 1]
    assert data["again"] == []


@node
def test_flush_packages_drained_events_and_reports_failures():
    data = _run_node(
        """
        const sink = createRecorder();
        sink.onKeyDown({ code: 'KeyC', key: 'c', repeat: false, isTrusted: true });
        const failed = flush(sink, { beacon: () => false, fetchPost: () => false });
        const sent = [];
        const okr = createRecorder();
        okr.onKeyDown({ code: 'KeyD', key: 'd', repeat: false, isTrusted: true });
        const ok = flush(okr, {
          beacon: (url, body) => { sent.push([url, JSON.parse(body).events.length]); return true; },
          fetchPost: () => { throw new Error('must not be called'); }
        });
        const empty = flush(createRecorder(), { beacon: () => false, fetchPost: () => false });
        process.stdout.write(JSON.stringify({ failed, ok, empty, sent, path: sdk.TELEMETRY_PATH }));
        """
    )
    assert data["failed"] == {"sent": 0, "error": "send-failed"}
    assert data["ok"]["sent"] == 1 and data["ok"]["error"] is None
    assert data["empty"] == {"sent": 0}
    assert data["sent"] == [["/__cadence/telemetry", 1]]
    assert data["path"] == "/__cadence/telemetry"


def test_boot_block_flushes_on_pagehide_and_interval():
    """Boot flushes on pagehide, a short interval, and submit (wait for ACK)."""
    from inject import BOOT_BLOCK

    assert 'addEventListener("pagehide"' in BOOT_BLOCK
    assert "setInterval(push, 500)" in BOOT_BLOCK
    assert 'fetch("/__cadence/telemetry"' in BOOT_BLOCK

