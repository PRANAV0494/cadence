"""Identity drift signal over the buffered keystroke stream. Pure functions.

The question: is the person (or machine) typing at the end of the session
still the one who was typing at the beginning? A hijacked session often
changes drivers mid-flight - the original human's typing is followed by an
attacker's, with different rhythm.

Approach: split the session's character keystrokes into an early window
(first N) and a late window (last N). For each of two independent
features - key dwell and flight time (inter-key interval) - compute a
standardized effect size (Cohen's d) between the windows. A drift signal
is raised only when BOTH features shift by a large effect: rhythm change
alone (someone slowing down) or dwell change alone (sticky keyboard, fatigue)
is not a driver change.

No fusion, no policy: this module returns a signal. What consumes it is
later work.
"""

from __future__ import annotations

import statistics

# Window size: first/last N character keydowns compared.
WINDOW = 20

# Cohen's d above this counts as a large shift (conventional threshold 0.8).
LARGE_EFFECT = 0.8


def _character_keydowns(events: list[dict]) -> list[dict]:
    downs = [
        e
        for e in events
        if e.get("event_type") == "keydown"
        and not e.get("is_modifier")
        and not e.get("is_paste")
    ]
    downs.sort(key=lambda e: e.get("timestamp", 0))
    return downs


def dwell_times(events: list[dict]) -> list[float]:
    """Durations of character-producing presses, matched by seq."""
    down_by_seq: dict[object, float] = {}
    for e in _character_keydowns(events):
        down_by_seq[e.get("seq")] = float(e.get("timestamp", 0))
    dwells = []
    for e in events:
        if e.get("event_type") != "keyup" or e.get("is_modifier") or e.get("is_paste"):
            continue
        seq = e.get("seq")
        if seq in down_by_seq:
            d = float(e.get("timestamp", 0)) - down_by_seq[seq]
            if d >= 0:
                dwells.append(d)
    return dwells


def flight_times(events: list[dict]) -> list[float]:
    """Inter-key intervals between successive character keydowns."""
    downs = _character_keydowns(events)
    return [
        float(b.get("timestamp", 0)) - float(a.get("timestamp", 0))
        for a, b in zip(downs, downs[1:])
    ]


def _effect_size(first: list[float], last: list[float]) -> float | None:
    """Cohen's d between two samples; None when not computable."""
    if len(first) < 2 or len(last) < 2:
        return None
    m1, m2 = statistics.mean(first), statistics.mean(last)
    s1, s2 = statistics.pstdev(first), statistics.pstdev(last)
    pooled = ((s1 * s1 + s2 * s2) / 2) ** 0.5
    if pooled == 0:
        # Both windows constant: identical constants are no drift, different
        # constants are unbounded drift. Use a small floor to avoid /0.
        if m1 == m2:
            return 0.0
        return float("inf")
    return abs(m2 - m1) / pooled


def drift_signal(events: list[dict], window: int = WINDOW) -> dict | None:
    """Compare the last `window` keystrokes to the first `window`.

    Returns {"drift": bool, "dwell_d": float, "flight_d": float} when there
    is enough data (at least 2*window dwell samples AND 2*window flights),
    else None. drift is True only when both features show a large effect.
    """
    dwells = dwell_times(events)
    flights = flight_times(events)
    if len(dwells) < 2 * window or len(flights) < 2 * window:
        return None
    dwell_d = _effect_size(dwells[:window], dwells[-window:])
    flight_d = _effect_size(flights[:window], flights[-window:])
    if dwell_d is None or flight_d is None:
        return None
    return {
        "drift": dwell_d > LARGE_EFFECT and flight_d > LARGE_EFFECT,
        "dwell_d": dwell_d,
        "flight_d": flight_d,
    }
