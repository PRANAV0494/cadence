"""
Tests for the edge injector: pure-function injection plus the CLI surface.
No mitmdump is started anywhere in this file.
"""

import sys
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

