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

# CV below this AND unique fraction below this → automated.
# Chosen against CMU-keyrec-style human distributions (CV >= 0.3 for any
# realistic passage) vs synthetic constant-rate streams (CV < 0.05).
# Conservative: both must be extreme simultaneously.
CV_THRESHOLD = 0.12
UNIQUE_FRACTION_THRESHOLD = 0.15

# Fewer character keydowns than this → not enough evidence for any verdict.
MIN_EVENTS = 10


def character_keydowns(events: list[dict]) -> list[dict]:
    """Character-producing keydowns in timestamp order."""
    downs = [
        e
        for e in events
        if e.get("event_type") == "keydown"
        and not e.get("is_modifier")
        and not e.get("is_paste")
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
    """CV and unique-interval fraction, or Nones when under MIN_EVENTS."""
    intervals = interkey_intervals(events)
    if len(intervals) < MIN_EVENTS - 1:
        return {"cv": None, "unique_fraction": None, "n": len(intervals)}
    mean = statistics.mean(intervals)
    if mean <= 0:
        return {"cv": None, "unique_fraction": None, "n": len(intervals)}
    stdev = statistics.pstdev(intervals)
    unique = len(set(intervals))
    return {
        "cv": stdev / mean,
        "unique_fraction": unique / len(intervals),
        "n": len(intervals),
    }


def is_automated(events: list[dict]) -> bool | None:
    """True = machine-like regularity. False = human-like. None = insufficient data.

    True only when BOTH signals are extreme: a fast but jittery human is
    never flagged on CV alone, and a paused-but-otherwise-synth stream
    (high unique fraction from think-time gaps) is never flagged on
    uniqueness alone.
    """
    m = automation_metrics(events)
    if m["cv"] is None:
        return None
    return m["cv"] < CV_THRESHOLD and m["unique_fraction"] < UNIQUE_FRACTION_THRESHOLD
