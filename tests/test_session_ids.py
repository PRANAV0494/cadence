"""Session-id hardness: unguessable minting, strict cookie parsing."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from provenance import new_session_id, session_key  # noqa: E402

_HEX32 = re.compile(r"[0-9a-f]{32}")


def test_minted_ids_are_128bit_hex():
    sid = new_session_id()
    assert _HEX32.fullmatch(sid), sid


def test_minted_ids_are_unique():
    assert len({new_session_id() for _ in range(100)}) == 100


def test_seeded_form_stays_deterministic_for_tests():
    assert new_session_id(1) == "0000000000000001"
    assert new_session_id(1) == new_session_id(1)


def test_huge_seed_still_passes_cookie_allowlist():
    sid = new_session_id(2**100)
    assert session_key(f"__cadence_sid={sid}", "fb") == sid


def test_oversized_cookie_falls_back():
    assert session_key("__cadence_sid=" + "a" * 200, "fb") == "fb"


def test_traversal_cookie_falls_back():
    assert session_key("__cadence_sid=../../etc/passwd", "fb") == "fb"


def test_valid_cookie_still_wins():
    assert session_key("__cadence_sid=deadbeef", "fb") == "deadbeef"
