"""Synthetic harness streams replay through cadence eval."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "edge"))

from cadence.eval import replay  # noqa: E402
from evaluation.harness.streams import (  # noqa: E402
    handoff,
    human_jitter,
    machine_constant,
    to_jsonl,
    untrusted_script,
)
from provenance import typed_string  # noqa: E402


def test_jsonl_roundtrip():
    blob = to_jsonl(human_jitter(5, seed=0))
    assert blob.count("\n") == 1
    assert '"events"' in blob


def test_machine_constant_flags_automation():
    result = replay(machine_constant(40))
    assert result["decision"] in ("step-up", "continue")
    # Constant 80ms gaps are the automation fixture; walk should not go clean.
    assert result["decision"] != "clean"


def test_untrusted_script_is_not_typed():
    rounds = untrusted_script(10)
    events = [e for r in rounds for e in r]
    assert typed_string(events) == ""


def test_handoff_has_two_flushes():
    assert len(handoff()) == 2
