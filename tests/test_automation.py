"""
Automation detector tests: a synthetic perfectly-timed stream must flag,
a human-like one must not. No ML, no training data — just interval
regularity.
"""

import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from automation import (  # noqa: E402
    CV_THRESHOLD,
    character_keydowns,
    MIN_EVENTS,
    UNIQUE_FRACTION_THRESHOLD,
    automation_metrics,
    character_keydowns,
    interkey_intervals,
    is_automated,
)


def _k(t: float, key: str = "a") -> dict:
    return {
        "event_type": "keydown",
        "is_modifier": False,
        "is_paste": False,
        "key": key,
        "timestamp": t,
    }


def synthetic_stream(n: int = 60, gap: float = 100.0) -> list[dict]:
    """A machine: every keydown exactly `gap` ms apart."""
    return [_k(i * gap, chr(97 + (i % 26))) for i in range(n)]


def human_stream(n: int = 60, seed: int = 42) -> list[dict]:
    """A human: jittered intervals with occasional pauses, deterministic."""
    rng = random.Random(seed)
    events = []
    t = 0.0
    for i in range(n):
        t += rng.uniform(60, 180)  # typing jitter
        if rng.random() < 0.08:
            t += rng.uniform(300, 900)  # think-time pause
        events.append(_k(t, chr(97 + (i % 26))))
    return events


# ── the headline cases ─────────────────────────────────────────

def test_perfectly_timed_stream_is_automated():
    assert is_automated(synthetic_stream()) is True


def test_human_like_stream_is_not_automated():
    assert is_automated(human_stream()) is False


def test_multiple_human_seeds_stay_human():
    for seed in (1, 7, 123, 2026):
        assert is_automated(human_stream(seed=seed)) is False, seed


# ── robustness ─────────────────────────────────────────────────

def test_short_streams_return_none():
    assert is_automated(synthetic_stream(n=5)) is None
    assert is_automated([]) is None


def test_modifiers_and_pastes_are_excluded():
    """Only character keydowns feed the intervals."""
    stream = synthetic_stream()
    noise = [
        {"event_type": "keydown", "is_modifier": True, "is_paste": False, "timestamp": 1.0},
        {"event_type": "keydown", "is_modifier": False, "is_paste": True, "timestamp": 2.0},
        {"event_type": "keyup", "timestamp": 3.0},
    ] * 5
    assert is_automated(stream + noise) is True  # noise does not dilute


def test_backspaces_are_excluded_from_intervals():
    """A synthetic stream plus backspace events still flags, and backspaces
    never appear in the interval series."""
    stream = synthetic_stream()
    backspaces = [
        {
            "event_type": "keydown",
            "is_modifier": False,
            "is_paste": False,
            "is_backspace": True,
            "key": "Backspace",
            "timestamp": 50.5 + i,
        }
        for i in range(10)
    ]
    assert is_automated(stream + backspaces) is True
    ts = [e["timestamp"] for e in character_keydowns(stream + backspaces)]
    assert all(t not in ts for t in [e["timestamp"] for e in backspaces])


def test_one_pause_no_longer_hides_a_machine():
    """[PR 18] A single 500 ms think-gap against 100 ms intervals used to
    drive whole-session CV to ~0.6 and hide the machine. Sliding windows
    score the clean stretch between pauses: the burst fires."""
    stream = synthetic_stream()
    for e in stream[30:]:
        e["timestamp"] += 500.0
    assert is_automated(stream) is True


def test_two_regular_bursts_separated_by_a_pause_now_flag():
    """[PR 18] Two clean 30-key bursts with one long gap: whole-stream CV
    was dominated by the gap; the window inside either burst is regular,
    so the stream fires."""
    burst1 = synthetic_stream(n=30, gap=100.0)
    offset = burst1[-1]["timestamp"] if burst1 else 0
    burst2 = synthetic_stream(n=30, gap=100.0)
    for e in burst2:
        e["timestamp"] += 3000.0 + offset
    assert is_automated(burst1 + burst2) is True


def test_metrics_shape():
    m = automation_metrics(synthetic_stream())
    assert m["n"] == 59  # whole-session interval count, for data sufficiency
    assert m["cv"] < 0.01  # best window: the whole stream is one clean burst
    assert m["unique_fraction"] < 0.10  # 1 distinct gap in a 15-interval window


def test_constants_are_conservative():
    """Both thresholds extreme, and MIN_EVENTS meaningful."""
    assert CV_THRESHOLD < 0.2
    assert UNIQUE_FRACTION_THRESHOLD < 0.3
    assert MIN_EVENTS >= 10
