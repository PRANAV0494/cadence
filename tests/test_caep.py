"""CAEP-shaped events: pinned event types and subjects, no network."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "edge"))

from cadence.policy.caep import (  # noqa: E402
    SESSION_REVOKED,
    TOKEN_CLAIMS_CHANGE,
    event,
    subject_id,
)


def test_event_uses_caep_session_revoked():
    e = event("abc", "provenance-unjustified", now=1_700_000_000)
    assert e["iss"] == "cadence"
    assert e["iat"] == 1_700_000_000
    assert e["sub_id"]["id"] == "abc"
    assert SESSION_REVOKED in e["events"]
    assert e["events"][SESSION_REVOKED]["reason"] == "provenance-unjustified"


def test_event_type_is_selectable_for_challenges():
    """A 401 step-up is a challenge, not a revocation; the type must be
    overridable without editing the payload by hand."""
    e = event("abc", "step-up", now=1_700_000_000, event_type=TOKEN_CLAIMS_CHANGE)
    assert TOKEN_CLAIMS_CHANGE in e["events"]
    assert SESSION_REVOKED not in e["events"]


def test_connection_fallback_subject_is_hashed():
    """A session key without a cookie is host|(ip, port). The client
    address must not leave the process inside a claimed-opaque subject."""
    key = "site.example|('192.0.2.7', 54321)"
    sub = subject_id(key)
    assert sub.startswith("conn-")
    assert "192.0.2.7" not in sub
    payload = json.dumps(event(key, "step-up", now=1_700_000_000))
    assert "192.0.2.7" not in payload
    assert "54321" not in payload


def test_cookie_sid_passes_through_unhashed():
    assert subject_id("00000000000000a1") == "00000000000000a1"
