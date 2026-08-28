"""Quantize keystroke timestamps to browser timer resolutions.

Literature uses lab-grade clocks. Browsers clamp `performance.now()`
(Firefox ~2 ms, Chrome ~100 µs, 100 ms under resistFingerprinting).
This module only quantizes; it does not report an EER. Plug the
output into an existing evaluator if you want a number with a source.
"""

from __future__ import annotations


RESOLUTIONS_MS = {
    "chrome_coarse": 0.1,
    "firefox": 2.0,
    "resist_fingerprinting": 100.0,
}


def quantize(timestamp_ms: float, step_ms: float) -> float:
    """Floor a timestamp onto a grid of `step_ms`."""
    if step_ms <= 0:
        raise ValueError("step_ms must be positive")
    return (timestamp_ms // step_ms) * step_ms


def quantize_events(events: list[dict], step_ms: float) -> list[dict]:
    """Copy events with timestamp fields snapped to the grid."""
    out = []
    for e in events:
        item = dict(e)
        ts = item.get("timestamp")
        if isinstance(ts, (int, float)):
            item["timestamp"] = quantize(float(ts), step_ms)
        out.append(item)
    return out
