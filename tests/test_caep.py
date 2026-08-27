"""CAEP-shaped events: pinned event type, no network."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cadence.policy.caep import SESSION_REVOKED, event  # noqa: E402


def test_event_uses_caep_session_revoked():
    e = event("abc", "provenance-unjustified", now=1_700_000_000)
    assert e["iss"] == "cadence"
    assert e["iat"] == 1_700_000_000
    assert e["sub_id"]["id"] == "abc"
    assert SESSION_REVOKED in e["events"]
    assert e["events"][SESSION_REVOKED]["reason"] == "provenance-unjustified"
