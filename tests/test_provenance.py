"""
Provenance tests: pure rules from edge/provenance.py plus the addon's
cookie / 403 / cap wiring, all with fake flows — no mitmdump started.
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

from provenance import (  # noqa: E402
    MAX_EVENTS_PER_SESSION,
    cap_session,
    count_keystrokes,
    post_has_text,
    post_is_justified,
    session_key,
    typed_string,
)

FORM = "application/x-www-form-urlencoded"

KEYDOWN = {"event_type": "keydown", "is_modifier": False, "is_paste": False}


# ── session_key ────────────────────────────────────────────────

def test_session_key_prefers_cookie():
    assert session_key("__cadence_sid=abc123; theme=dark", "fb") == "abc123"


def test_session_key_falls_back_without_cookie():
    assert session_key(None, "fb") == "fb"
    assert session_key("theme=dark", "fb") == "fb"
    assert session_key("__cadence_sid=; other=1", "fb") == "fb"  # empty value ignored


# ── post_has_text ──────────────────────────────────────────────

def test_text_field_with_letters_counts():
    assert post_has_text(b"message=hello+world", FORM) is True
    assert post_has_text(b"q=what+is+keystroke+dynamics", FORM) is True


def test_digits_only_is_not_text():
    assert post_has_text(b"message=123456", FORM) is False


def test_password_is_never_the_trigger():
    """Managers and browsers type passwords; they must not cause a 403."""
    assert post_has_text(b"password=hunter2secret", FORM) is False
    assert post_has_text(b"username=bob&password=hunter2secret", FORM) is False


def test_non_form_bodies_are_out_of_scope():
    assert post_has_text(b'{"message": "hello"}', "application/json") is False
    assert post_has_text(b"hello", "text/plain") is False
    assert post_has_text(b"message=hello", None) is False


def test_empty_body_is_not_text():
    assert post_has_text(b"", FORM) is False


def test_any_script_counts_as_text():
    assert post_has_text("message=नमस्ते".encode(), FORM) is True
    assert post_has_text("message=こんにちは".encode(), FORM) is True


# ── the policy ─────────────────────────────────────────────────

def test_text_post_with_zero_keystrokes_is_unjustified():
    assert post_is_justified(b"message=hello", FORM, []) is False


def test_text_post_with_keystrokes_is_justified():
    hello = [
        {"event_type": "keydown", "is_modifier": False, "is_paste": False, "key": c}
        for c in "hello"
    ]
    assert post_is_justified(b"message=hello", FORM, hello) is True


def test_non_text_post_passes_without_keystrokes():
    """The gate only binds text-bearing form POSTs."""
    assert post_is_justified(b"otp=123456", FORM, []) is True
    assert post_is_justified(b"agree=true", FORM, []) is True


def test_modifier_or_paste_events_do_not_justify():
    """Only character-producing keydowns count as typed input."""
    events = [
        {"event_type": "keydown", "is_modifier": True, "is_paste": False},
        {"event_type": "keydown", "is_modifier": False, "is_paste": True},
        {"event_type": "keyup"},
    ]
    assert count_keystrokes(events) == 0
    assert post_is_justified(b"message=hello", FORM, events) is False


# ── typed-string reconstruction ────────────────────────────────

def _k(key: str, **kw) -> dict:
    base = {"event_type": "keydown", "is_modifier": False, "is_paste": False, "key": key}
    base.update(kw)
    return base


def test_typed_string_reconstructs_characters():
    assert typed_string([_k(c) for c in "hello"]) == "hello"


def test_enter_in_textarea_is_a_newline():
    events = [_k("h"), _k("Enter", is_modifier=True), _k("i")]
    assert typed_string(events) == "h\ni"
    assert post_is_justified(b"message=h%0Ai", FORM, events) is True


def test_spacebar_key_name_is_a_space():
    events = [_k("h"), _k("Spacebar", is_modifier=True), _k("i")]
    assert typed_string(events) == "h i"


def test_backspace_pops_the_last_character():
    assert typed_string([_k("h"), _k("e"), _k("y"), _k("Backspace", is_backspace=True)]) == "he"


def test_modifiers_and_pastes_are_skipped():
    assert (
        typed_string([_k("Shift", is_modifier=True), _k("a"), _k(None, is_paste=True)])
        == "a"
    )


# ── substring provenance ───────────────────────────────────────

def test_typed_hello_justifies_message_hello():
    assert post_is_justified(b"message=hello", FORM, [_k(c) for c in "hello"]) is True


def test_typed_single_h_does_not_justify_hello():
    """One stray keydown must not justify arbitrary text."""
    assert post_is_justified(b"message=hello", FORM, [_k("h")]) is False


def test_urldecoding_applies_before_matching():
    assert (
        post_is_justified(b"message=hello+world", FORM, [_k(c) for c in "hello world"])
        is True
    )


def test_multiple_text_fields_must_all_be_typed():
    events = [_k(c) for c in "hello"]
    assert post_is_justified(b"title=hi&message=hello", FORM, events) is False
    assert (
        post_is_justified(b"title=hi&message=hello", FORM, [_k(c) for c in "hi hello"])
        is True
    )


# ── cap ────────────────────────────────────────────────────────

def test_cap_keeps_the_recent_tail():
    events = list(range(15))
    assert cap_session(events, limit=10) == list(range(5, 15))


def test_cap_is_a_noop_under_the_limit():
    events = list(range(5))
    assert cap_session(events, limit=10) == events


def test_cap_default_is_the_module_constant():
    assert cap_session([]) == []
    assert MAX_EVENTS_PER_SESSION == 10_000


# ── addon wiring, with fake flows ──────────────────────────────

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


class _Response:
    def __init__(self, content=b"", content_type="text/html"):
        self.content = content
        self.headers = _Headers(
            {"Content-Type": content_type, "Content-Length": "999"}
        )


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


def _telemetry_flow(cookie=None, events=None):
    headers = {"cookie": cookie} if cookie else {}
    body = json.dumps({"events": events or []}).encode()
    return _Flow(_Request("/__cadence/telemetry", body, headers=headers))


def test_html_response_seeds_session_cookie(monkeypatch):
    addon = _load_addon()
    flow = _Flow(_Request("/page"))
    flow.response = _Response(b"<html><body></body></html>")
    addon.addons[0].response(flow)

    set_cookie = flow.response.headers.get("Set-Cookie")
    assert set_cookie and set_cookie.startswith("__cadence_sid=")
    assert b'id="cadence-sdk"' in flow.response.content  # injection still happens


def test_existing_sid_is_not_rotated():
    """The first version minted a new sid per HTML response: telemetry stayed
    under the old id, the POST saw an empty buffer, humans got 403'd."""
    addon = _load_addon()
    flow = _Flow(_Request("/page", headers={"cookie": "__cadence_sid=keepme"}))
    flow.response = _Response(b"<html><body></body></html>")
    addon.addons[0].response(flow)

    set_cookie = flow.response.headers.get("Set-Cookie")
    assert set_cookie is None  # existing sid kept, nothing re-issued


def test_missing_sid_is_minted_once():
    addon = _load_addon()
    flow = _Flow(_Request("/page"))
    flow.response = _Response(b"<html><body></body></html>")
    addon.addons[0].response(flow)

    set_cookie = flow.response.headers.get("Set-Cookie")
    assert set_cookie and set_cookie.startswith("__cadence_sid=")
    assert "SameSite=Lax" in set_cookie


def test_telemetry_204_also_seeds_a_missing_sid(monkeypatch):
    """A beacon can arrive before any HTML response minted the cookie."""
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _telemetry_flow(events=[KEYDOWN])  # no cookie on the request
    addon.addons[0].request(flow)

    assert flow.response is not None
    set_cookie = flow.response.headers.get("Set-Cookie")
    assert set_cookie and set_cookie.startswith("__cadence_sid=")
    # and the buffer keyed under the freshly minted id, not the peer fallback
    (key,) = addon.sessions.keys()
    assert key in set_cookie


def test_telemetry_buffers_under_cookie_session(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    addon.addons[0].request(_telemetry_flow(cookie="__cadence_sid=deadbeef", events=[KEYDOWN]))

    assert list(addon.sessions.keys()) == ["deadbeef"]
    assert addon.sessions["deadbeef"] == [KEYDOWN]


def test_text_post_without_keystrokes_is_blocked_with_403(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _Flow(
        _Request(
            "/post-comment",
            b"message=hello+world",
            headers={
                "cookie": "__cadence_sid=deadbeef",
                "content-type": FORM,
            },
        )
    )
    addon.addons[0].request(flow)

    assert flow.response is not None
    assert flow.response.status_code == 403
    assert flow.response.content.startswith(b"cadence:")  # our block, not upstream's


def test_text_post_with_keystrokes_goes_through(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    addon.addons[0].request(
        _telemetry_flow(
            cookie="__cadence_sid=deadbeef",
            events=[
                {"event_type": "keydown", "is_modifier": False, "is_paste": False, "key": c}
                for c in "hello world"
            ],
        )
    )
    flow = _Flow(
        _Request(
            "/post-comment",
            b"message=hello+world",
            headers={
                "cookie": "__cadence_sid=deadbeef",
                "content-type": FORM,
            },
        )
    )
    addon.addons[0].request(flow)

    assert flow.response is None  # forwarded upstream, not answered locally


def test_password_only_post_is_not_blocked(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _Flow(
        _Request(
            "/login",
            b"username=bob&password=hunter2secret",
            headers={
                "cookie": "__cadence_sid=deadbeef",
                "content-type": FORM,
            },
        )
    )
    addon.addons[0].request(flow)

    assert flow.response is None


def test_non_post_method_is_never_blocked(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    flow = _Flow(_Request("/post-comment?message=hello", b"", method="GET"))
    addon.addons[0].request(flow)

    assert flow.response is None


def test_telemetry_applies_the_cap(monkeypatch):
    addon = _load_addon()
    addon.sessions.clear()
    _fake_mitmproxy(monkeypatch)

    burst = [dict(KEYDOWN, seq=i) for i in range(MAX_EVENTS_PER_SESSION + 50)]
    addon.addons[0].request(_telemetry_flow(cookie="__cadence_sid=c", events=burst))

    buffered = addon.sessions["c"]
    assert len(buffered) == MAX_EVENTS_PER_SESSION
    assert buffered[0]["seq"] == 50  # stale head dropped, recent tail kept
