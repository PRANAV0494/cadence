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


def human_jitter(
    n: int = 40, seed: int = 1, start: float = 0.0, seq_offset: int = 0
) -> list[list[dict]]:
    rng = random.Random(seed)
    t = start
    seq = seq_offset
    flush: list[dict] = []
    for _ in range(n):
        gap = rng.uniform(80.0, 280.0)
        dwell = rng.uniform(40.0, 120.0)
        t += gap
        flush.extend(_down_up(seq, "a", t, dwell))
        seq += 1
    return [flush]


def machine_constant(
    n: int = 40, gap: float = 80.0, start: float = 0.0, seq_offset: int = 0
) -> list[list[dict]]:
    t = start
    seq = seq_offset
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


def handoff(
    human_n: int = 30, machine_n: int = 30, seed: int = 2, gap_ms: float = 700.0
) -> list[list[dict]]:
    """Human flush, then a constant machine flush — a takeover mid-session.

    The machine's clock starts after the human's last event and its seqs
    continue from the human's: detectors sort by timestamp and pair by
    seq, so two flushes both starting at t=0 / seq=0 would interleave
    into one mixed stream and the labelled takeover would replay clean.
    """
    human = human_jitter(human_n, seed)
    last_t = max(e["timestamp"] for e in human[0])
    machine = machine_constant(
        machine_n, start=last_t + gap_ms, seq_offset=human_n
    )
    return human + machine


def to_jsonl(rounds: list[list[dict]]) -> str:
    return "".join(json.dumps({"events": r}) + "\n" for r in rounds)
