"""Dwell gate: seq-paired character presses, fail on negative-heavy files."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evaluation.check_dwell import dwells_ms, main, report  # noqa: E402


def _pair(seq, key, t_down, dwell):
    base = {
        "seq": seq,
        "key": key,
        "is_modifier": False,
        "is_paste": False,
        "is_backspace": False,
    }
    return [
        {**base, "event_type": "keydown", "timestamp": t_down},
        {**base, "event_type": "keyup", "timestamp": t_down + dwell},
    ]


def test_dwells_pair_by_seq_not_order():
    # Rollover: press b before releasing a. Interleaved in time: a down,
    # b down, a up, b up.
    events = [
        {"event_type": "keydown", "seq": 0, "key": "a", "timestamp": 0.0,
         "is_modifier": False, "is_paste": False, "is_backspace": False},
        {"event_type": "keydown", "seq": 1, "key": "b", "timestamp": 30.0,
         "is_modifier": False, "is_paste": False, "is_backspace": False},
        {"event_type": "keyup", "seq": 0, "key": "a", "timestamp": 80.0,
         "is_modifier": False, "is_paste": False, "is_backspace": False},
        {"event_type": "keyup", "seq": 1, "key": "b", "timestamp": 80.0,
         "is_modifier": False, "is_paste": False, "is_backspace": False},
    ]
    assert dwells_ms(events) == [80.0, 50.0]


def test_report_passes_positive_humanish(tmp_path):
    events = []
    t = 0.0
    for i in range(12):
        events.extend(_pair(i, "a", t, 70.0 + i))
        t += 150.0
    p = tmp_path / "ok.jsonl"
    p.write_text(json.dumps({"events": events}) + "\n", encoding="utf-8")
    r = report(p)
    assert r["ok"] is True
    assert r["median_ms"] > 0
    assert main([str(p)]) == 0


def test_report_fails_negative_dwell_bug(tmp_path):
    events = []
    for i in range(12):
        events.extend(_pair(i, "a", 100.0, -200.0))
    p = tmp_path / "buggy.jsonl"
    p.write_text(json.dumps({"events": events}) + "\n", encoding="utf-8")
    r = report(p)
    assert r["ok"] is False
    assert r["median_ms"] < 0
    assert main([str(p)]) == 1


def test_seq_none_events_are_skipped():
    base = {"key": "a", "is_modifier": False, "is_paste": False, "is_backspace": False}
    events = [
        {**base, "event_type": "keydown", "seq": None, "timestamp": 0.0},
        {**base, "event_type": "keyup", "seq": None, "timestamp": 80.0},
        *_pair(0, "a", 100.0, 70.0),
    ]
    assert dwells_ms(events) == [70.0]
