"""Untrusted (is_trusted=False) events do not count as typing."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"
sys.path.insert(0, str(EDGE))

from automation import character_keydowns, is_automated  # noqa: E402
from provenance import post_is_justified, typed_string  # noqa: E402

FORM = "application/x-www-form-urlencoded"


def _k(key, trusted=True, t=0):
    return {
        "event_type": "keydown",
        "is_modifier": False,
        "is_paste": False,
        "is_backspace": False,
        "key": key,
        "timestamp": t,
        "is_trusted": trusted,
        "seq": t,
    }


def test_untrusted_keydowns_are_not_typed():
    events = [_k("h", True), _k("i", False)]
    assert typed_string(events) == "h"


def test_scripted_fill_does_not_justify_text():
    events = [_k(c, trusted=False, t=i) for i, c in enumerate("hello")]
    assert post_is_justified(b"message=hello", FORM, events) is False


def test_missing_is_trusted_still_counts():
    e = _k("a")
    del e["is_trusted"]
    assert typed_string([e]) == "a"


def test_untrusted_stream_is_not_automation_evidence():
    events = [_k("a", trusted=False, t=i * 80) for i in range(40)]
    assert character_keydowns(events) == []
    assert is_automated(events) is None
