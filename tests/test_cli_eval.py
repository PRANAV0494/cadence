"""
cadence eval tests: replay JSONL through detectors + fusion, decision and
time-to-detect. No mitmdump; the replay is pure.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "edge"))

from cadence import eval as eval_module  # noqa: E402


def _burst(n, gap, dwell, start=0.0, seq_offset=0):
    events = []
    t = start
    for i in range(n):
        events.append({"event_type": "keydown", "seq": seq_offset + i,
                       "is_modifier": False, "is_paste": False, "key": "a",
                       "timestamp": t})
        events.append({"event_type": "keyup", "seq": seq_offset + i,
                       "is_modifier": False, "is_paste": False, "key": "a",
                       "timestamp": t + dwell})
        t += gap
    return events


def _human(n=60, seed=42, start=0.0):
    import random
    rng = random.Random(seed)
    events = []
    t = start
    for i in range(n):
        events.append({"event_type": "keydown", "seq": i, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t})
        events.append({"event_type": "keyup", "seq": i, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t + rng.uniform(60, 120)})
        t += rng.uniform(60, 180)
    return events


def _write_jsonl(tmp_path, rounds):
    lines = [json.dumps({"events": r}) for r in rounds]
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_machine_session_replays_to_step_up(tmp_path):
    p = _write_jsonl(tmp_path, [_burst(30, 100.0, 80.0)])
    result = eval_module.main([str(p)])
    assert result == 0


def test_replay_result_shapes(tmp_path):
    rounds = [_burst(30, 100.0, 80.0)]
    result = eval_module.replay(rounds)
    assert result["decision"] in ("step-up", "clean", "continue")
    assert result["rounds"] == 1
    assert result["history"][0]["decision"] == "step-up"  # automation fires round 1
    assert result["time_to_detect_ms"] is not None
    assert result["time_to_detect_ms"] >= 0


def test_sticky_step_up_survives_a_continue_round():
    """Once step-up, only clean clears. Round 2 has unchanged flags so
    update() would say continue; the result must stay step-up."""
    machine = _burst(30, 100.0, 80.0)
    more = _burst(30, 100.0, 80.0, start=90000.0, seq_offset=100)
    result = eval_module.replay([machine, more])
    assert result["history"][0]["decision"] == "step-up"
    assert result["decision"] == "step-up"


def test_human_session_decision_follows_loaded_rates():
    """A single human round banks automation-silent + drift-silent
    evidence. Whether that clears depends entirely on the loaded
    DETECTOR_RATES vs the bounds - assert the arithmetic, never a
    hardcoded terminal state."""
    import math

    from fusion import DETECTOR_RATES, bounds

    def llr_of(name, fired):
        tpr, fpr = DETECTOR_RATES[name]
        return math.log(tpr / fpr) if fired else math.log((1 - tpr) / (1 - fpr))

    result = eval_module.replay([_human()])
    expected = llr_of("automation", False) + llr_of("drift", False)
    assert abs(result["history"][-1]["llr"] - expected) < 0.001
    lo, hi = bounds()
    final = result["history"][-1]["llr"]
    expected_decision = (
        "step-up" if final >= hi else "clean" if final <= lo else "continue"
    )
    assert result["decision"] == expected_decision


def test_takeover_evidence_follows_loaded_rates():
    """Short human round, then a sharp takeover. Whether it crosses
    depends on the loaded rates - assert the walk's arithmetic and the
    decision against the bounds, never a hardcoded terminal."""
    import math

    from fusion import DETECTOR_RATES, bounds

    def llr_of(name, fired):
        tpr, fpr = DETECTOR_RATES[name]
        return math.log(tpr / fpr) if fired else math.log((1 - tpr) / (1 - fpr))

    short_human = _human(n=20, seed=7)
    start = max(e["timestamp"] for e in short_human) + 700.0
    takeover = _burst(40, 40.0, 30.0, start=start, seq_offset=500)
    result = eval_module.replay([short_human, takeover])

    assert result["history"][1]["llr"] > result["history"][0]["llr"]  # attack added
    lo, hi = bounds()
    final = result["history"][-1]["llr"]
    expected_decision = (
        "step-up" if final >= hi else "clean" if final <= lo else "continue"
    )
    assert result["decision"] == expected_decision



def test_bare_event_lines_are_accepted(tmp_path):
    lines = [json.dumps(e) for e in _burst(10, 100.0, 80.0)]
    p = tmp_path / "bare.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rounds = eval_module._rounds(p.read_text(encoding="utf-8").splitlines())
    assert len(rounds) == 20  # 10 presses -> 20 bare event lines
    assert all(len(r) == 1 for r in rounds)


def test_malformed_lines_are_skipped(tmp_path):
    good = json.dumps({"events": _burst(12, 100.0, 80.0)})
    p = tmp_path / "mixed.jsonl"
    p.write_text("not json\n\n" + good + "\n", encoding="utf-8")
    rounds = eval_module._rounds(p.read_text(encoding="utf-8").splitlines())
    assert len(rounds) == 1


def test_missing_file_fails_cleanly(capsys):
    assert eval_module.main(["nope.jsonl"]) == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_lists_eval(capsys):
    from cadence import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "eval" in capsys.readouterr().out
