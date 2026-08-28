"""Synthetic harness streams replay through cadence eval."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "edge"))

from automation import is_automated  # noqa: E402
from cadence.eval import replay  # noqa: E402
from evaluation.harness.streams import (  # noqa: E402
    handoff,
    human_jitter,
    machine_constant,
    to_jsonl,
    untrusted_script,
)

WIRE_FIELDS = {"event_type", "seq", "code", "key", "timestamp",
               "is_backspace", "is_modifier", "is_paste", "is_trusted"}


def test_jsonl_roundtrip():
    blob = to_jsonl(human_jitter(5, seed=0))
    assert blob.count("\n") == 1
    assert '"events"' in blob


def test_machine_constant_flags_automation():
    events = [e for r in machine_constant(40) for e in r]
    assert is_automated(events) is True
    # The labelled machine class must reach the terminal the walk owns.
    assert replay(machine_constant(40))["decision"] == "step-up"


def test_human_jitter_stays_automation_silent():
    events = [e for r in human_jitter(40) for e in r]
    assert is_automated(events) is False
    assert replay(human_jitter(40))["decision"] == "clean"


def test_untrusted_script_events_are_marked_untrusted():
    """The property this harness owns: every emitted event carries
    is_trusted False alongside the full wire shape. What consumers DO
    with untrusted events (drop from typed_string) is pinned where that
    filter lives, not here."""
    rounds = untrusted_script(10)
    events = [e for r in rounds for e in r]
    assert events
    for e in events:
        assert e["is_trusted"] is False
        assert WIRE_FIELDS <= e.keys()


def test_handoff_is_a_takeover_not_an_interleave():
    """The machine flush strictly follows the human flush: monotonic
    timestamps across the boundary, no seq collisions. Two flushes both
    starting at t=0/seq=0 would sort into one mixed stream and the
    labelled takeover would replay clean — a harness false negative."""
    rounds = handoff()
    assert len(rounds) == 2
    human, machine = rounds
    assert min(e["timestamp"] for e in machine) > max(e["timestamp"] for e in human)
    keys = [(e["seq"], e["event_type"]) for e in human + machine]
    assert len(set(keys)) == len(keys)


def test_handoff_replay_does_not_stay_clean():
    result = replay(handoff())
    # Round 0 (human alone) may legitimately clear; the takeover round
    # must reverse that — the walk ends challenged, never clean.
    assert result["decision"] == "step-up"
    assert result["history"][-1]["decision"] == "step-up"
