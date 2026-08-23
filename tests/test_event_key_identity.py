"""
Regression tests for keystroke event pairing.

These cover the defect that invalidated the first round of collected data:
events were keyed by caret position, so each keydown was matched with the
previous character's keyup. 85% of recorded human dwell times came out negative
(median -285.5 ms), and a downstream classifier reached 1.0 accuracy by learning
`dwell < 0` — a measurement of the bug, not of behaviour.

The two failure modes are different, and both are tested:

  Sequential typing (press, release, gap, press...) is where the defect showed
  up as negative dwell. Keydown i+1 lands after keyup i, so the mis-pairing
  computes `t_up[i] - t_down[i+1]`, which is negative by construction. Verified
  against a faithful replay of the old scheme: 3/3 negative.

  Rollover (next key pressed before the previous is released) is the dangerous
  one. There the same mis-pairing yields *plausible positive* values — 50 ms,
  20 ms — that look like real dwell times and pass any sanity check. Verified:
  0/2 negative.

That split explains the collected data: 85% of human samples negative, the rest
positive-looking rollover artefacts. A validity check alone would have caught
the 85% but silently accepted the rest, so correctness is enforced by pairing on
press identity, not by filtering outputs.
"""

import pytest

from cadence.features.keystroke import (
    CorruptEventStreamError,
    _parse_events,
    extract_features,
)


def kd(seq, code, ts, **kw):
    return {
        "event_type": "keydown", "seq": seq, "code": code, "key": code[-1].lower(),
        "timestamp": ts, "is_backspace": False, "is_paste": False, **kw,
    }


def ku(seq, code, ts, **kw):
    return {
        "event_type": "keyup", "seq": seq, "code": code, "key": code[-1].lower(),
        "timestamp": ts, "is_backspace": False, "is_paste": False, **kw,
    }


def test_sequential_typing_yields_exact_dwell_times():
    """
    Non-overlapping presses: dwell is release minus press, per key.

    Under the old caret-index scheme this same input produced [-110, -115, -88]
    — the negative-dwell signature that corrupted 85% of collected samples.
    """
    events = [
        kd(0, "KeyC", 0.0), ku(0, "KeyC", 90.0),
        kd(1, "KeyA", 200.0), ku(1, "KeyA", 285.0),
        kd(2, "KeyT", 400.0), ku(2, "KeyT", 512.0),
    ]
    _, _, dwell, flight = _parse_events(events)

    assert dwell == [90.0, 85.0, 112.0]
    # release of key i -> press of key i+1
    assert flight == [110.0, 115.0]


def test_rollover_pairs_each_press_with_its_own_release():
    """
    The case that silently produced wrong-but-believable numbers.

    'A' is pressed at 0 and held until 150. 'B' is pressed at 100 — before 'A'
    is released — and released at 180. Correct dwell: A = 150, B = 80.

    The old caret-index scheme returned [50, 20] here: positive, plausible, and
    wrong. No range check would have rejected it. Only pairing each release with
    the press it belongs to gives the right answer.
    """
    events = [
        kd(0, "KeyA", 0.0),
        kd(1, "KeyB", 100.0),
        ku(0, "KeyA", 150.0),
        ku(1, "KeyB", 180.0),
    ]
    _, _, dwell, _ = _parse_events(events)

    assert dwell == [150.0, 80.0]
    assert all(d > 0 for d in dwell)


def test_three_key_rollover():
    """Deeper overlap: releases arrive in a different order than presses."""
    events = [
        kd(0, "KeyT", 0.0),
        kd(1, "KeyH", 60.0),
        kd(2, "KeyE", 110.0),
        ku(1, "KeyH", 140.0),   # H released first
        ku(0, "KeyT", 170.0),   # then T
        ku(2, "KeyE", 200.0),
    ]
    _, _, dwell, _ = _parse_events(events)

    assert dwell == [170.0, 80.0, 90.0]


def test_legacy_caret_indexed_stream_is_rejected():
    """
    A stream with no `seq` cannot be paired correctly and must not be parsed
    into features. Silently producing corrupt numbers is what caused the
    original problem.
    """
    legacy = [
        {"event_type": "keydown", "key_index": 0, "key": "a", "timestamp": 0.0,
         "is_backspace": False, "is_paste": False},
        {"event_type": "keyup", "key_index": 1, "key": "a", "timestamp": 90.0,
         "is_backspace": False, "is_paste": False},
    ]
    with pytest.raises(CorruptEventStreamError, match="no 'seq' field"):
        _parse_events(legacy)


def test_negative_dwell_is_rejected():
    """A key released before it was pressed is physically impossible."""
    events = [kd(0, "KeyA", 200.0), ku(0, "KeyA", 50.0)]
    with pytest.raises(CorruptEventStreamError, match="negative"):
        _parse_events(events)


def test_keyup_without_matching_keydown_is_dropped_not_mispaired():
    """
    A release whose press was never captured carries seq=None. It must be
    ignored rather than attached to some other press.
    """
    events = [
        ku(None, "KeyX", 10.0),    # press happened before capture began
        kd(0, "KeyA", 100.0), ku(0, "KeyA", 190.0),
    ]
    _, _, dwell, _ = _parse_events(events)

    assert dwell == [90.0]


def test_unreleased_press_contributes_no_dwell():
    """Still-held key at submit time: no release, so no dwell sample."""
    events = [
        kd(0, "KeyA", 0.0), ku(0, "KeyA", 80.0),
        kd(1, "KeyB", 150.0),  # never released
    ]
    _, _, dwell, _ = _parse_events(events)

    assert dwell == [80.0]


def test_extract_features_reports_positive_dwell_statistics():
    """End-to-end: the summary statistics that were corrupted are now sane."""
    events = []
    ts = 0.0
    for i, code in enumerate(["KeyH", "KeyE", "KeyL", "KeyL", "KeyO"]):
        events.append(kd(i, code, ts))
        events.append(ku(i, code, ts + 85.0 + i))
        ts += 190.0

    feats = extract_features(events)

    assert feats["variability_features"]["mean_dwell_time"] > 0
    assert feats["distribution_features"]["median_dwell_time"] > 0
    assert feats["distribution_features"]["min_dwell_time"] > 0
    assert all(d > 0 for d in feats["core_features"]["per_key_dwell_times"])
    assert feats["core_features"]["typing_speed_wpm"] > 0


# ── client-supplied identity must be validated server-side ─────

def test_duplicate_press_identity_is_rejected():
    """
    seq is a press identity, and it comes from the browser. Two keydowns
    sharing one both paired with the same keyup, counting one dwell sample
    twice — accepted silently before.
    """
    events = [kd(0, "KeyA", 0.0), kd(0, "KeyB", 10.0), ku(0, "KeyA", 100.0)]
    with pytest.raises(CorruptEventStreamError, match="Duplicate press identity"):
        _parse_events(events)


def test_partially_stamped_stream_is_rejected():
    """
    The legacy guard fired only when *every* keydown lacked seq, so a mixed
    stream had those presses silently dropped from dwell. The SDK stamps every
    keydown, so a gap means corruption or tampering.
    """
    events = [
        kd(0, "KeyA", 0.0), ku(0, "KeyA", 90.0),
        {"event_type": "keydown", "code": "KeyB", "key": "b", "timestamp": 200.0,
         "is_backspace": False, "is_paste": False},
    ]
    with pytest.raises(CorruptEventStreamError, match="have no 'seq'"):
        _parse_events(events)


def test_non_character_keys_are_excluded_from_timing():
    """Tab, Escape, Arrow keys and F-keys produce no text."""
    events = [
        {**kd(0, "Tab", 0.0), "is_modifier": True},
        {**ku(0, "Tab", 120.0), "is_modifier": True},
        kd(1, "KeyA", 200.0), ku(1, "KeyA", 285.0),
    ]
    _, _, dwell, _ = _parse_events(events)

    assert dwell == [85.0]


def test_backspace_ratio_counts_characters_not_modifiers():
    """
    total_keys counted every keydown including Shift, so holding Shift for
    capitals diluted the denominator without adding any text.
    """
    events = [
        {**kd(0, "ShiftLeft", 0.0), "is_modifier": True},
        {**ku(0, "ShiftLeft", 300.0), "is_modifier": True},
        kd(1, "KeyA", 50.0), ku(1, "KeyA", 135.0),
        {**kd(2, "Backspace", 400.0), "is_backspace": True},
        {**ku(2, "Backspace", 480.0), "is_backspace": True},
    ]
    feats = extract_features(events)

    # Shift is out of the denominator; the backspace stays in, because a
    # correction rate measured against characters alone can exceed 1.
    # One character + one backspace = 2 text-affecting presses, 1 correction.
    assert feats["error_features"]["backspace_ratio"] == 0.5
    # Counting the Shift press too would have given 1/3.
    assert feats["error_features"]["backspace_count"] == 1
