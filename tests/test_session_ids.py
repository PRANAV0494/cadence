"""Session-id hardness: unguessable minting, strict cookie parsing."""

import re
import secrets
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

import provenance  # noqa: E402
from provenance import new_session_id, session_key  # noqa: E402

_HEX32 = re.compile(r"[0-9a-f]{32}")


def test_minted_ids_are_128bit_hex():
    sid = new_session_id()
    assert _HEX32.fullmatch(sid), sid


def test_minted_ids_are_unique():
    assert len({new_session_id() for _ in range(100)}) == 100


def test_determinism_comes_from_patching_the_entropy_source(monkeypatch):
    """No seed parameter: a test-only argument on a security primitive is a
    production call site waiting to happen. Patch the source instead."""
    monkeypatch.setattr(provenance.secrets, "token_hex", lambda n: "ab" * n)
    assert new_session_id() == "ab" * 16
    assert new_session_id() == new_session_id()


def test_minted_id_passes_its_own_cookie_allowlist():
    sid = new_session_id()
    assert session_key(f"__cadence_sid={sid}", "fb") == sid


def test_id_is_drawn_from_secrets_not_random(monkeypatch):
    """Guards against a refactor swapping in the `random` module."""
    calls = []
    real = secrets.token_hex
    monkeypatch.setattr(provenance.secrets, "token_hex",
                        lambda n: (calls.append(n), real(n))[1])
    new_session_id()
    assert calls == [16], "expected one 16-byte draw from secrets.token_hex"


def test_oversized_cookie_falls_back():
    assert session_key("__cadence_sid=" + "a" * 200, "fb") == "fb"


def test_traversal_cookie_falls_back():
    assert session_key("__cadence_sid=../../etc/passwd", "fb") == "fb"


def test_dot_only_cookie_falls_back():
    """'.' and '..' fullmatched the allowlist before (?!\\.+$)."""
    for value in (".", "..", "..."):
        assert session_key(f"__cadence_sid={value}", "fb") == "fb", value


def test_valid_cookie_still_wins():
    assert session_key("__cadence_sid=deadbeef", "fb") == "deadbeef"
