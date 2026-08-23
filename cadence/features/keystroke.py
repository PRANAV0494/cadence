"""
Feature extraction module for keystroke dynamics.

Accepts a list of raw KeystrokeEvent dicts and computes 30+ behavioural
biometric features grouped into seven categories.
"""

import math
from typing import List, Dict, Any, Tuple
from collections import defaultdict

# ── Utilities ──────────────────────────────────────────────────

def _safe_mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def _safe_std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _safe_mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))

def _safe_median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]

def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)

def _skewness(values: List[float]) -> float:
    n = len(values)
    if n < 3:
        return 0.0
    m = _safe_mean(values)
    s = _safe_std(values)
    if s == 0:
        return 0.0
    return (n / ((n - 1) * (n - 2))) * sum(((v - m) / s) ** 3 for v in values)

def _kurtosis(values: List[float]) -> float:
    n = len(values)
    if n < 4:
        return 0.0
    m = _safe_mean(values)
    s = _safe_std(values)
    if s == 0:
        return 0.0
    k4 = sum(((v - m) / s) ** 4 for v in values) / n
    return k4 - 3.0  # excess kurtosis

def _coefficient_of_variation(values: List[float]) -> float:
    m = _safe_mean(values)
    if m == 0:
        return 0.0
    return _safe_std(values) / abs(m)

def _entropy(values: List[float], bins: int = 10) -> float:
    """Compute Shannon entropy of a distribution."""
    if not values:
        return 0.0
    mn, mx = min(values), max(values)
    if mn == mx:
        return 0.0
    bin_width = (mx - mn) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - mn) / bin_width), bins - 1)
        counts[idx] += 1
    total = len(values)
    ent = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            ent -= p * math.log2(p)
    return ent


# ── Event Parsing ──────────────────────────────────────────────

class CorruptEventStreamError(ValueError):
    """Raised when an event stream cannot yield physically valid timings."""


def _press_id(event: Dict[str, Any]) -> Any:
    """
    Stable identity of a single key press.

    `seq` is assigned by the capture SDK: a monotonic counter stamped on keydown
    and echoed on the matching keyup. It is the only field that survives key
    rollover, where a fast typist presses the next key before releasing the
    previous one, so presses overlap and cannot be paired by ordering.

    Legacy streams carry `key_index` (a caret position) instead. That field is
    not key identity — the caret sits before the inserted character on keydown
    and after it on keyup — so pairing on it matches each press with the
    *previous* character's release and yields negative dwell times. Such streams
    are rejected in _parse_events rather than silently mis-parsed.
    """
    return event.get("seq")


def _parse_events(events: List[Dict[str, Any]]) -> Tuple[
    List[Dict], List[Dict], List[float], List[float]
]:
    """
    Separate keydown/keyup events and compute per-key dwell times
    and flight times.

    Raises CorruptEventStreamError if the stream predates the `seq` field or
    produces negative dwell times, which are physically impossible.
    """
    # Modifiers are excluded from timing statistics. A Shift held across a
    # capital letter dwells several times longer than the letter itself, and
    # counting it as a character inflates typing speed. Measured on a synthetic
    # sample: mean dwell 202.5 ms vs 85.0 ms, WPM 62.3 vs 32.0, and digraphs
    # degenerate into Shift-A / A-Shift pairs. The events are still present in
    # the stream for detectors that want modifier behaviour as a signal.
    def _is_character_press(e: Dict[str, Any]) -> bool:
        return not (e.get("is_backspace") or e.get("is_paste") or e.get("is_modifier"))

    keydowns = sorted(
        [e for e in events if e["event_type"] == "keydown" and _is_character_press(e)],
        key=lambda e: e["timestamp"],
    )
    keyups = sorted(
        [e for e in events if e["event_type"] == "keyup" and _is_character_press(e)],
        key=lambda e: e["timestamp"],
    )

    if keydowns and all(_press_id(e) is None for e in keydowns):
        raise CorruptEventStreamError(
            "Event stream has no 'seq' field. Streams captured before the "
            "key-identity fix paired keydowns with the previous character's "
            "keyup; their dwell-derived features are unusable. Re-collect with "
            "edge/cadence-sdk.js."
        )

    # Match keydown → keyup by press identity.
    up_map: Dict[Any, float] = {}
    for e in keyups:
        pid = _press_id(e)
        if pid is not None:
            up_map[pid] = e["timestamp"]

    dwell_times: List[float] = []
    for e in keydowns:
        up_ts = up_map.get(_press_id(e))
        if up_ts is not None:
            dwell_times.append(up_ts - e["timestamp"])

    # Flight time: release of key i to press of key i+1. Negative under
    # rollover, which is normal and informative — it measures overlap.
    flight_times: List[float] = []
    for i in range(len(keydowns) - 1):
        up_ts = up_map.get(_press_id(keydowns[i]))
        if up_ts is not None:
            flight_times.append(keydowns[i + 1]["timestamp"] - up_ts)

    negative = [d for d in dwell_times if d < 0]
    if negative:
        raise CorruptEventStreamError(
            f"{len(negative)} of {len(dwell_times)} dwell times are negative "
            f"(min {min(negative):.1f} ms). A key cannot be released before it "
            f"is pressed; the event stream is mis-paired."
        )

    return keydowns, keyups, dwell_times, flight_times


# ── Feature Groups ─────────────────────────────────────────────

def _core_features(
    keydowns: List[Dict], dwell_times: List[float], flight_times: List[float]
) -> Dict[str, Any]:
    """Per-key dwell, flight, inter-key latency, total duration, WPM."""
    inter_key = []
    for i in range(len(keydowns) - 1):
        inter_key.append(keydowns[i + 1]["timestamp"] - keydowns[i]["timestamp"])

    total_duration = 0.0
    if keydowns:
        total_duration = keydowns[-1]["timestamp"] - keydowns[0]["timestamp"]

    # Approximate WPM: total chars / 5 = words, duration in minutes
    num_chars = len(keydowns)
    duration_min = total_duration / 60000.0 if total_duration > 0 else 1.0
    wpm = (num_chars / 5.0) / duration_min if duration_min > 0 else 0.0

    return {
        "per_key_dwell_times": dwell_times,
        "per_key_flight_times": flight_times,
        "inter_key_latencies": inter_key,
        "total_typing_duration_ms": round(total_duration, 2),
        "typing_speed_wpm": round(wpm, 2),
    }


def _variability_features(
    dwell_times: List[float], flight_times: List[float], keydowns: List[Dict]
) -> Dict[str, Any]:
    """Statistical variability measures."""
    # Rolling window variance (window=5)
    window = 5
    rolling_vars: List[float] = []
    for i in range(len(dwell_times) - window + 1):
        chunk = dwell_times[i : i + window]
        rolling_vars.append(_safe_std(chunk) ** 2)

    # Session speed drift: compare first-half vs second-half mean latency
    inter_key = []
    for i in range(len(keydowns) - 1):
        inter_key.append(keydowns[i + 1]["timestamp"] - keydowns[i]["timestamp"])
    mid = len(inter_key) // 2
    first_half = _safe_mean(inter_key[:mid]) if mid > 0 else 0.0
    second_half = _safe_mean(inter_key[mid:]) if mid > 0 else 0.0
    speed_drift = second_half - first_half

    return {
        "mean_dwell_time": round(_safe_mean(dwell_times), 4),
        "std_dwell_time": round(_safe_std(dwell_times), 4),
        "mean_flight_time": round(_safe_mean(flight_times), 4),
        "std_flight_time": round(_safe_std(flight_times), 4),
        "coefficient_of_variation": round(_coefficient_of_variation(dwell_times), 4),
        "rolling_window_variance": [round(v, 4) for v in rolling_vars],
        "session_speed_drift_ms": round(speed_drift, 4),
    }


def _distribution_features(dwell_times: List[float]) -> Dict[str, Any]:
    """Distribution shape metrics."""
    return {
        "median_dwell_time": round(_safe_median(dwell_times), 4),
        "min_dwell_time": round(min(dwell_times), 4) if dwell_times else 0.0,
        "max_dwell_time": round(max(dwell_times), 4) if dwell_times else 0.0,
        "skewness": round(_skewness(dwell_times), 4),
        "kurtosis": round(_kurtosis(dwell_times), 4),
        "iqr": round(_percentile(dwell_times, 75) - _percentile(dwell_times, 25), 4),
    }


def _digraph_features(keydowns: List[Dict], dwell_times: List[float]) -> Dict[str, Any]:
    """Digraph (key-pair) timing features."""
    digraph_latencies: Dict[str, List[float]] = defaultdict(list)

    for i in range(len(keydowns) - 1):
        pair = f"{keydowns[i]['key']}-{keydowns[i + 1]['key']}"
        latency = keydowns[i + 1]["timestamp"] - keydowns[i]["timestamp"]
        digraph_latencies[pair].append(latency)

    # Mean per-digraph
    digraph_means = {pair: round(_safe_mean(vals), 4) for pair, vals in digraph_latencies.items()}
    all_latencies = [v for vals in digraph_latencies.values() for v in vals]

    # Consistency: lower std relative to mean = more consistent
    consistency = 0.0
    if all_latencies:
        m = _safe_mean(all_latencies)
        s = _safe_std(all_latencies)
        consistency = 1.0 - min(_coefficient_of_variation(all_latencies), 1.0)

    return {
        "digraph_latencies": digraph_means,
        "mean_digraph_latency": round(_safe_mean(all_latencies), 4),
        "std_digraph_latency": round(_safe_std(all_latencies), 4),
        "digraph_consistency_score": round(consistency, 4),
    }


def _pause_features(keydowns: List[Dict]) -> Dict[str, Any]:
    """Detect and analyse pauses in typing."""
    inter_key = []
    for i in range(len(keydowns) - 1):
        inter_key.append(keydowns[i + 1]["timestamp"] - keydowns[i]["timestamp"])

    pauses = [t for t in inter_key if t > 300]
    long_pauses = [t for t in inter_key if t > 700]

    # Pause position pattern: normalised positions (0-1) of pauses
    pause_positions: List[float] = []
    total = len(inter_key)
    for i, t in enumerate(inter_key):
        if t > 300:
            pause_positions.append(round(i / total, 4) if total > 0 else 0.0)

    return {
        "pause_count": len(pauses),
        "long_pause_count": len(long_pauses),
        "average_pause_length_ms": round(_safe_mean(pauses), 4),
        "pause_position_pattern": pause_positions,
    }


def _error_features(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Backspace / correction metrics."""
    all_events_sorted = sorted(events, key=lambda e: e["timestamp"])

    total_keys = len([e for e in events if e["event_type"] == "keydown"])
    backspaces = [e for e in events if e.get("is_backspace") and e["event_type"] == "keydown"]
    backspace_count = len(backspaces)
    backspace_ratio = backspace_count / total_keys if total_keys > 0 else 0.0

    # Correction burst: consecutive backspaces
    burst_lengths: List[int] = []
    current_burst = 0
    for e in all_events_sorted:
        if e["event_type"] == "keydown":
            if e.get("is_backspace"):
                current_burst += 1
            else:
                if current_burst > 0:
                    burst_lengths.append(current_burst)
                current_burst = 0
    if current_burst > 0:
        burst_lengths.append(current_burst)

    # Correction latency: time between last normal key and first backspace of a burst
    correction_latencies: List[float] = []
    prev_normal_ts = None
    for e in all_events_sorted:
        if e["event_type"] == "keydown":
            if not e.get("is_backspace"):
                prev_normal_ts = e["timestamp"]
            elif prev_normal_ts is not None:
                correction_latencies.append(e["timestamp"] - prev_normal_ts)
                prev_normal_ts = None  # only count first in burst

    return {
        "backspace_ratio": round(backspace_ratio, 4),
        "correction_burst_length": round(_safe_mean(burst_lengths), 4) if burst_lengths else 0.0,
        "correction_latency_ms": round(_safe_mean(correction_latencies), 4),
        "backspace_count": backspace_count,
    }


def _sequence_features(
    dwell_times: List[float], keydowns: List[Dict]
) -> Dict[str, Any]:
    """Temporal sequence / rhythm features."""
    inter_key = []
    for i in range(len(keydowns) - 1):
        inter_key.append(keydowns[i + 1]["timestamp"] - keydowns[i]["timestamp"])

    # Autocorrelation (lag-1)
    autocorr = 0.0
    if len(inter_key) > 2:
        m = _safe_mean(inter_key)
        num = sum((inter_key[i] - m) * (inter_key[i + 1] - m) for i in range(len(inter_key) - 1))
        den = sum((v - m) ** 2 for v in inter_key)
        autocorr = num / den if den > 0 else 0.0

    # Burst typing score: fraction of inter-key intervals < 100ms
    burst_count = sum(1 for t in inter_key if t < 100)
    burst_score = burst_count / len(inter_key) if inter_key else 0.0

    # Acceleration trend: slope of inter-key latencies
    accel = 0.0
    if len(inter_key) > 1:
        n = len(inter_key)
        x_mean = (n - 1) / 2.0
        y_mean = _safe_mean(inter_key)
        num = sum((i - x_mean) * (inter_key[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        accel = num / den if den > 0 else 0.0

    # Timing entropy
    timing_ent = _entropy(inter_key) if inter_key else 0.0

    return {
        "autocorrelation_score": round(autocorr, 4),
        "burst_typing_score": round(burst_score, 4),
        "acceleration_trend": round(accel, 4),
        "timing_entropy": round(timing_ent, 4),
    }


# ── Public API ─────────────────────────────────────────────────

def extract_features(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Main entry point.  Accepts raw keystroke event dicts and returns
    a nested dict of all computed feature groups.
    """
    keydowns, keyups, dwell_times, flight_times = _parse_events(events)

    core = _core_features(keydowns, dwell_times, flight_times)
    variability = _variability_features(dwell_times, flight_times, keydowns)
    distribution = _distribution_features(dwell_times)
    digraph = _digraph_features(keydowns, dwell_times)
    pause = _pause_features(keydowns)
    error = _error_features(events)
    sequence = _sequence_features(dwell_times, keydowns)

    return {
        "core_features": core,
        "variability_features": variability,
        "distribution_features": distribution,
        "digraph_features": digraph,
        "pause_features": pause,
        "error_features": error,
        "sequence_features": sequence,
    }
