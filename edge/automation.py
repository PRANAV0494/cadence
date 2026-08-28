"""Automation detection on the buffered keystroke stream. Pure functions.

No ML training, no models: machines type with near-constant intervals,
humans do not. The detector measures interval regularity over the
character-producing keydowns of a session and reports a likelihood-style
score plus a boolean verdict.

Two independent regularity signals, both required for a verdict:

  * Coefficient of variation (CV) of inter-key intervals: std/mean.
    Human typing lands roughly 0.3-0.7; a synth firing every k ms is ~0.
  * Unique-interval fraction: |unique intervals| / |intervals|.
    Humans quantize less; a synth produces very few distinct gaps.

Thresholds are deliberately conservative (only flag extreme regularity),
because the cost of a false "automation" verdict downstream is a human
being asked to step up authentication.
"""

from __future__ import annotations

import statistics

from trusted import is_trusted

# CV below this AND unique fraction below this → automated.
# Chosen against CMU-keyrec-style human distributions (CV >= 0.3 for any
# realistic passage) vs synthetic constant-rate streams (CV < 0.05).
# Conservative: both must be extreme simultaneously.
CV_THRESHOLD = 0.12
UNIQUE_FRACTION_THRESHOLD = 0.15

# Fewer character keydowns than this → not enough evidence for any verdict.
MIN_EVENTS = 10

# Burst-window detection: regularity is scored inside sliding windows of
# this many intervals, not only over the whole session. A single
# think-time pause inflates whole-session CV enough to hide an otherwise
# synthetic stream (tested, documented); a window sliding over the
# interval series finds the machine-clean stretch between pauses.
WINDOW = 15


def character_keydowns(events: list[dict]) -> list[dict]:
    """Character-producing keydowns in timestamp order.

    Backspaces are excluded with the same rule provenance uses: a backspace
    is not a typed character, and counting it as one would let a machine
    interleave deletions and still count as 'human-jittered' intervals.
    """
    downs = [
        e
        for e in events
        if e.get("event_type") == "keydown"
        and not e.get("is_modifier")
        and not e.get("is_paste")
        and not e.get("is_backspace")
        and is_trusted(e)
    ]
    downs.sort(key=lambda e: e.get("timestamp", 0))
    return downs


def interkey_intervals(events: list[dict]) -> list[float]:
    """Successive timestamp deltas over character keydowns, in ms."""
    downs = character_keydowns(events)
    return [
        float(b.get("timestamp", 0)) - float(a.get("timestamp", 0))
        for a, b in zip(downs, downs[1:])
    ]


def automation_metrics(events: list[dict]) -> dict:
    """CV and unique-interval fraction, or Nones when under MIN_EVENTS.

    The metrics are the best (most regular) sliding window, not the whole
    session: burst windows are what catches a machine separated by pauses.
    `n` stays the whole-session interval count for the data-sufficiency
    contract.
    """
    intervals = interkey_intervals(events)
    if len(intervals) < MIN_EVENTS - 1:
        return {"cv": None, "unique_fraction": None, "n": len(intervals)}
    best = None
    for start in range(0, max(1, len(intervals) - WINDOW + 1)):
        window = intervals[start : start + WINDOW]
        if len(window) < MIN_EVENTS - 1:
            break
        mean = statistics.mean(window)
        if mean <= 0:
            continue
        cv = statistics.pstdev(window) / mean
        unique_fraction = len(set(window)) / len(window)
        score = cv + unique_fraction  # lower = more regular
        if best is None or score < best[0]:
            best = (score, cv, unique_fraction)
    if best is None:
        return {"cv": None, "unique_fraction": None, "n": len(intervals)}
    return {"cv": best[1], "unique_fraction": best[2], "n": len(intervals)}


def is_automated(events: list[dict]) -> bool | None:
    """True = machine-like regularity in ANY window. False = human-like.
    None = insufficient data.

    The verdict uses the most-regular sliding window, so a machine whose
    stream is split by think-time pauses still fires. True requires BOTH
    signals extreme within that window: a fast but jittery human is never
    flagged on CV alone, and a quantized-but-varied typist never on
    uniqueness alone.
    """
    m = automation_metrics(events)
    if m["cv"] is None:
        return None
    return m["cv"] < CV_THRESHOLD and m["unique_fraction"] < UNIQUE_FRACTION_THRESHOLD
