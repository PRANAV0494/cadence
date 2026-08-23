"""
CSP tests: the injected scripts must survive a strict Content-Security-Policy.

The hash tokens are only correct if they cover the exact bytes between the
<script> tags as inject() emits them. These tests hash real inject() output
and require the addon's CSP rewrite to carry those hashes.
"""

import base64
import hashlib
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from inject import BOOT_BLOCK, csp_hashes, inject, script_bodies  # noqa: E402

SDK = (EDGE / "cadence-sdk.js").read_text(encoding="utf-8")


def _load_addon():
    import addon  # noqa: E402
    return addon


class _Headers(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


def _html_flow(csp=None):
    class _Req:
        host = "site.example"
        method = "GET"
        path = "/page"
        raw_content = b""
        headers = _Headers({})

    class _Conn:
        peername = ("127.0.0.1", 1111)

    class _Flow:
        def __init__(self):
            self.request = _Req()
            self.client_conn = _Conn()
            self.response = _Resp()

    class _Resp:
        def __init__(self):
            self.content = b"<html><body></body></html>"
            self.headers = _Headers(
                {"Content-Type": "text/html", "Content-Length": "31"}
                | ({"Content-Security-Policy": csp} if csp else {})
            )

    return _Flow()


def _sha256_token(data: bytes) -> str:
    """Quoted, as CSP grammar requires: 'sha256-<b64>'."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode("ascii") + "'"


# ── hash correctness, pinned against real inject() output ──────

def test_csp_hashes_match_real_injected_output():
    result = inject(b"<html><body></body></html>", SDK).decode("utf-8")
    tokens = csp_hashes(SDK)
    assert len(tokens) == 2

    # Extract each script body exactly as emitted, between its tags.
    first_start = result.index('<script id="cadence-sdk">') + len('<script id="cadence-sdk">')
    first_end = result.index("</script>", first_start)
    second_start = result.index('<script id="cadence-sdk-boot">') + len('<script id="cadence-sdk-boot">')
    second_end = result.index("</script>", second_start)

    assert _sha256_token(result[first_start:first_end].encode("utf-8")) == tokens[0]
    assert _sha256_token(result[second_start:second_end].encode("utf-8")) == tokens[1]


def test_script_bodies_are_the_bytes_between_the_tags():
    result = inject(b"<html><body></body></html>", SDK)
    for body, token in zip(script_bodies(SDK), csp_hashes(SDK)):
        assert body in result
        assert _sha256_token(body) == token


# ── addon CSP rewrite ──────────────────────────────────────────

def test_strict_csp_gets_our_hashes_appended():
    addon = _load_addon()
    flow = _html_flow("script-src 'self'")
    addon.addons[0].response(flow)

    csp = flow.response.headers.get("Content-Security-Policy")
    for token in csp_hashes(SDK):
        assert token in csp
    assert "script-src 'self'" in csp  # page's own policy preserved


def test_hashes_append_to_default_src_when_no_script_src():
    addon = _load_addon()
    flow = _html_flow("default-src 'self'; img-src 'self'")
    addon.addons[0].response(flow)

    csp = flow.response.headers.get("Content-Security-Policy")
    parts = [p.strip() for p in csp.split(";")]
    default = next(p for p in parts if p.startswith("default-src"))
    for token in csp_hashes(SDK):
        assert token in default
    img = next(p for p in parts if p.startswith("img-src"))
    assert csp_hashes(SDK)[0] not in img  # only script/default touched


def test_no_csp_header_means_no_rewrite():
    addon = _load_addon()
    flow = _html_flow(None)
    addon.addons[0].response(flow)

    assert flow.response.headers.get("Content-Security-Policy") is None
    assert b'id="cadence-sdk"' in flow.response.content


def test_existing_hash_is_not_duplicated():
    addon = _load_addon()
    csp = f"script-src 'self' {csp_hashes(SDK)[0]}"
    flow = _html_flow(csp)
    addon.addons[0].response(flow)

    rewritten = flow.response.headers.get("Content-Security-Policy")
    assert rewritten.count(csp_hashes(SDK)[0]) == 1


def test_policy_without_script_governance_is_untouched():
    addon = _load_addon()
    flow = _html_flow("img-src 'self'; style-src 'self'")
    addon.addons[0].response(flow)

    assert (
        flow.response.headers.get("Content-Security-Policy")
        == "img-src 'self'; style-src 'self'"
    )


def test_unsafe_inline_means_no_hash_appended():
    """
    CSP2+ turns 'unsafe-inline' OFF on a directive once any hash/nonce
    appears in it. Appending hashes to a policy that relies on
    'unsafe-inline' would break the page's own inline scripts — while
    adding nothing, since 'unsafe-inline' already permits ours.
    """
    addon = _load_addon()
    original = "script-src 'self' 'unsafe-inline'"
    flow = _html_flow(original)
    addon.addons[0].response(flow)

    assert flow.response.headers.get("Content-Security-Policy") == original
    assert "sha256" not in flow.response.headers.get("Content-Security-Policy")


def test_unsafe_inline_in_an_untargeted_directive_still_gets_hashes():
    """The skip decision is on the governing directive only."""
    addon = _load_addon()
    flow = _html_flow("img-src 'self' 'unsafe-inline'; script-src 'self'")
    addon.addons[0].response(flow)

    csp = flow.response.headers.get("Content-Security-Policy")
    for token in csp_hashes(SDK):
        assert token in csp
    assert "img-src 'self' 'unsafe-inline'" in csp  # untouched


def test_hashes_are_single_quoted():
    """Unquoted sha256-... tokens are ignored by browsers."""
    for token in csp_hashes(SDK):
        assert token.startswith("'sha256-") and token.endswith("'")
