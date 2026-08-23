"""
Identity drift tests: a mid-session change of driver must raise a signal;
the same typist throughout must not.
"""

import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from drift import drift_signal, dwell_times, flight_times  # noqa: E402


def _presses(intervals, dwells, start=0.0, seq_offset=0):
    """Build an event stream from flight intervals and dwell times.

    Each key i: keydown at t_i, keyup at t_i + dwell_i. The keydown for
    key i+1 happens `intervals[i]` after keydown i (flight time).
    seq_offset shifts press identities so concatenated fixtures keep the
    per-session uniqueness the real SDK guarantees.
    """
    events = []
    t = start
    for i, (gap, dwell) in enumerate(zip(intervals, dwells)):
        seq = seq_offset + i
        events.append(
            {
                "event_type": "keydown",
                "seq": seq,
                "is_modifier": False,
                "is_paste": False,
                "key": "a",
                "timestamp": t,
            }
        )
        events.append(
            {
                "event_type": "keyup",
                "seq": seq,
                "is_modifier": False,
                "is_paste": False,
                "key": "a",
                "timestamp": t + dwell,
            }
        )
        t += gap
    return events


def _human(n=80, mean_gap=120.0, mean_dwell=90.0, seed=42):
    rng = random.Random(seed)
    gaps = [max(20.0, rng.gauss(mean_gap, mean_gap * 0.35)) for _ in range(n)]
    dwells = [max(20.0, rng.gauss(mean_dwell, mean_dwell * 0.25)) for _ in range(n)]
    return _presses(gaps, dwells)


def _typist(n=80, gap_mean=120.0, dwell_mean=90.0, seed=7):
    return _human(n=n, mean_gap=gap_mean, mean_dwell=dwell_mean, seed=seed)


# ── stream construction sanity ─────────────────────────────────

def test_dwell_and_flight_extraction():
    events = _presses([100.0, 150.0], [80.0, 60.0])
    assert dwell_times(events) == [80.0, 60.0]
    assert flight_times(events) == [100.0]  # 2 presses -> 1 flight


# ── the headline cases ─────────────────────────────────────────

def test_same_typist_throughout_no_drift():
    assert drift_signal(_human(seed=1))["drift"] is False


def test_multiple_same_typist_seeds_no_drift():
    for seed in (1, 2, 3, 4, 5):
        assert drift_signal(_human(seed=seed))["drift"] is False, seed


def test_mid_session_driver_change_raises_drift():
    """First half: 120 ms gaps / 90 ms dwells. Second half: a much faster,
    snappier driver — 45 ms gaps / 35 ms dwells."""
    first = _typist(n=50, gap_mean=120.0, dwell_mean=90.0, seed=11)
    # Shift the second driver onto the first's timeline
    offset = max(e["timestamp"] for e in first) + 500.0
    second = _presses(
        [max(20.0, random.Random(12).gauss(45.0, 12.0)) for _ in range(50)],
        [max(15.0, random.Random(13).gauss(35.0, 8.0)) for _ in range(50)],
        start=offset,
        seq_offset=100,
    )
    result = drift_signal(first + second)
    assert result is not None
    assert result["drift"] is True


def test_gradual_fatigue_ramp_is_not_drift():
    """Real fatigue is gradual: a linear ramp from 120->150 ms gaps and
    90->105 ms dwells over the whole session. A step is a driver change;
    a ramp spreads the change across the session so first-vs-last windows
    see a modest shift, not a large one."""
    rng = random.Random(22)
    n = 100
    gaps, dwells = [], []
    t_gaps, t_dwells = 0.0, 0.0
    for i in range(n):
        f = i / (n - 1)
        gap_mean = 120.0 + 30.0 * f
        dwell_mean = 90.0 + 15.0 * f
        gaps.append(max(20.0, rng.gauss(gap_mean, gap_mean * 0.35)))
        dwells.append(max(20.0, rng.gauss(dwell_mean, dwell_mean * 0.25)))
    result = drift_signal(_presses(gaps, dwells))
    assert result is not None
    assert result["drift"] is False, result


def test_abrupt_step_slowdown_is_drift():
    """The same magnitude of change as a STEP (not a ramp) IS flagged.
    A driver change in practice means a different person or tool at the
    keyboard: ~2x dwell and flight shifts, applied abruptly. Fatigue never
    looks like this — it ramps."""
    first = _typist(n=50, gap_mean=120.0, dwell_mean=90.0, seed=21)
    offset = max(e["timestamp"] for e in first) + 500.0
    slower = _presses(
        [max(20.0, random.Random(23).gauss(220.0, 66.0)) for _ in range(50)],
        [max(20.0, random.Random(24).gauss(160.0, 40.0)) for _ in range(50)],
        start=offset,
        seq_offset=100,
    )
    result = drift_signal(first + slower)
    assert result["drift"] is True, result


# ── insufficient data ──────────────────────────────────────────

def test_short_session_returns_none():
    assert drift_signal(_human(n=10)) is None
    assert drift_signal([]) is None


def test_result_shape():
    r = drift_signal(_human())
    assert set(r) == {"drift", "dwell_d", "flight_d"}
