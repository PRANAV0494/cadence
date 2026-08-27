"""Build labelled JSONL sessions: human-jitter, constant machine, handoff.

Each line is a flush of events in the SDK wire format, so `cadence eval`
replays it the same way the proxy would.
"""

from __future__ import annotations

import json
import random


def _down_up(seq: int, key: str, t: float, dwell: float, trusted: bool = True) -> list[dict]:
    base = {
        "seq": seq,
        "code": f"Key{key.upper()}",
        "key": key,
        "is_backspace": False,
        "is_modifier": False,
        "is_paste": False,
        "is_trusted": trusted,
    }
    return [
        {**base, "event_type": "keydown", "timestamp": t},
        {**base, "event_type": "keyup", "timestamp": t + dwell},
    ]


def human_jitter(n: int = 40, seed: int = 1) -> list[list[dict]]:
    rng = random.Random(seed)
    t = 0.0
    seq = 0
    flush: list[dict] = []
    for _ in range(n):
        gap = rng.uniform(80.0, 280.0)
        dwell = rng.uniform(40.0, 120.0)
        t += gap
        flush.extend(_down_up(seq, "a", t, dwell))
        seq += 1
    return [flush]


def machine_constant(n: int = 40, gap: float = 80.0) -> list[list[dict]]:
    t = 0.0
    seq = 0
    flush: list[dict] = []
    for _ in range(n):
        t += gap
        flush.extend(_down_up(seq, "a", t, 40.0))
        seq += 1
    return [flush]


def untrusted_script(n: int = 20) -> list[list[dict]]:
    """dispatchEvent-style keydowns: is_trusted false."""
    t = 0.0
    seq = 0
    flush: list[dict] = []
    for _ in range(n):
        t += 90.0
        flush.extend(_down_up(seq, "a", t, 40.0, trusted=False))
        seq += 1
    return [flush]


def handoff(human_n: int = 30, machine_n: int = 30, seed: int = 2) -> list[list[dict]]:
    """Human flush, then a constant machine flush — a takeover mid-session."""
    return human_jitter(human_n, seed) + machine_constant(machine_n)


def to_jsonl(rounds: list[list[dict]]) -> str:
    return "".join(json.dumps({"events": r}) + "\n" for r in rounds)
