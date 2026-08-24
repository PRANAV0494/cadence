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


def test_human_session_is_cleared():
    """With measured (smoothed) rates one honest round is decisive
    evidence: automation-silent and drift-silent at ~0.99/0.97 tpr means
    silence is strong honesty evidence, and the walk clears. That is
    correct SPRT with confident rates - 'continue' was the placeholder-
    rate expectation."""
    result = eval_module.replay([_human()])
    assert result["decision"] == "clean"
    assert result["time_to_detect_ms"] is not None


def test_takeover_overcomes_a_short_clean_start():
    """A full human round banks ~-8 nats of clean evidence; a takeover
    supplies drift (+4.6) and automation (+4.6) = +9.2, landing at +1.1 -
    continue, not step-up (one-shot: unchanged flags add nothing more).
    That is the honest arithmetic at measured rates. With a SHORT human
    round the same takeover crosses: less clean banked, same attack.
    Both behaviors pinned."""
    short_human = _human(n=20, seed=7)
    start = max(e["timestamp"] for e in short_human) + 700.0
    takeover = _burst(40, 40.0, 30.0, start=start, seq_offset=500)
    result = eval_module.replay([short_human, takeover])
    assert result["decision"] == "step-up"
    assert result["time_to_detect_ms"] >= start


def test_full_human_then_takeover_stays_continue():
    """The full-human-then-takeover arithmetic: -8.1 + 9.2 = +1.1,
    between the bounds. Not step-up - and that is the SPRT's honest
    answer with confident rates, not a bug to paper over."""
    human = _human()
    start = max(e["timestamp"] for e in human) + 700.0
    takeover = _burst(40, 40.0, 30.0, start=start, seq_offset=500)
    result = eval_module.replay([human, takeover])
    assert result["decision"] == "continue"


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
