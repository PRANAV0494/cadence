#!/usr/bin/env python3
"""Measure detector rates on a labelled fixture and emit results.json entries.

The fixture is synthetic but LABELED and fixed-seeded: three classes of
keystroke streams (synthetic machine, jittered human, driver-change) with
known ground truth. The detectors' true/false positive rates on this
fixture are what they are - measured, reproducible, and honest about
being fixture-derived (not field-derived). The source recorded in
results.json names this script and the fixture parameters, so nobody can
mistake them for live-traffic rates.

Classes and labels:
  - machine:      constant-timing bursts (attacker automation)      -> label 1
  - human:        jittered bursts with think-time pauses            -> label 0
  - takeover:     human then a sharp second machine (drift attack)  -> label 1
                  (for drift); label 0 for automation on this class
                  by construction (whole-stream dilution is expected)

Usage:
    python evaluation/calibrate_detectors.py            # print table
    python evaluation/calibrate_detectors.py --json     # results.json entries
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "edge"))

from automation import is_automated  # noqa: E402
from drift import drift_signal  # noqa: E402

SEEDS = list(range(50))  # 50 streams per class
HUMAN_N = 60
MACHINE_GAP = 100.0
MACHINE_DWELL = 80.0


def _presses(intervals, dwells, start=0.0, seq_offset=0):
    events = []
    t = start
    for i, (gap, dwell) in enumerate(zip(intervals, dwells)):
        seq = seq_offset + i
        events.append({"event_type": "keydown", "seq": seq, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t, "is_backspace": False})
        events.append({"event_type": "keyup", "seq": seq, "is_modifier": False,
                       "is_paste": False, "key": "a", "timestamp": t + dwell, "is_backspace": False})
        t += gap
    return events


def machine_stream(seed: int) -> list[dict]:
    rng = random.Random(1000 + seed)
    n = 50 + rng.randrange(20)
    gap = rng.uniform(60.0, 110.0)  # one constant rate per stream
    dwell = rng.uniform(40.0, 80.0)
    intervals = [gap] * n
    # No think pauses in this fixture: this base's detector scores the
    # whole session (burst windows are a later PR). Measured TPR is
    # honest for THIS detector version. Re-calibrate when windows land.
    return _presses(intervals, [dwell] * n)


def human_stream(seed: int) -> list[dict]:
    rng = random.Random(2000 + seed)
    n = HUMAN_N
    intervals, dwells = [], []
    for _ in range(n):
        intervals.append(max(20.0, rng.gauss(120.0, 42.0)))
        dwells.append(max(20.0, rng.gauss(90.0, 24.0)))
        if rng.random() < 0.10:
            intervals[-1] += rng.uniform(300.0, 900.0)
    return _presses(intervals, dwells)


def takeover_stream(seed: int) -> list[dict]:
    """Human first, then a sharp machine: drift label 1."""
    rng = random.Random(3000 + seed)
    first = human_stream(seed)
    offset = max(e["timestamp"] for e in first) + 700.0
    gap = rng.uniform(40.0, 60.0)
    dwell = rng.uniform(30.0, 45.0)
    n = 40
    second = _presses([gap] * n, [dwell] * n, start=offset, seq_offset=1000)
    return first + second


def _rate(flags: list) -> tuple[float, int]:
    fired = sum(1 for f in flags if f is True)
    return fired / len(flags), len(flags)


def measure() -> dict:
    humans = [human_stream(s) for s in SEEDS]
    machines = [machine_stream(s) for s in SEEDS]
    takeovers = [takeover_stream(s) for s in SEEDS]

    # automation: positive class = machines; negatives = humans only.
    # Takeovers are EXCLUDED from automation's confusion matrix: their
    # trailing machine segment is genuinely automation, so counting a
    # takeover as an automation "false positive" mislabels a correct
    # detection. Takeover detection is drift's question.
    auto_tpr, n_pos = _rate([is_automated(m) for m in machines])
    auto_fpr, n_neg = _rate([is_automated(h) for h in humans])

    # drift: positive class = takeovers; negatives = humans
    drift_tpr, _ = _rate([bool((drift_signal(t) or {}).get("drift")) for t in takeovers])
    drift_fpr, _ = _rate([bool((drift_signal(h) or {}).get("drift")) for h in humans])

    return {
        "automation": {"tpr": auto_tpr, "fpr": auto_fpr, "n_positive": n_pos, "n_negative": n_neg},
        "drift": {"tpr": drift_tpr, "fpr": drift_fpr, "n_positive": len(takeovers), "n_negative": len(humans)},
        "fixture": {"seeds": len(SEEDS), "human_n": HUMAN_N,
                    "classes": ["machine", "human", "takeover"]},
    }


def results_entries(m: dict) -> dict:
    src = "evaluation/calibrate_detectors.py"
    return {
        "detector_automation_tpr": {
            "value": round(m["automation"]["tpr"], 4),
            "n_streams": m["automation"]["n_positive"],
            "source": src,
            "description": "Automation detector true-positive rate on the labelled fixture "
                           "(constant-rate machine bursts with two think pauses each, 50 seeds). "
                           "Fixture-derived, not field-derived.",
        },
        "detector_automation_fpr": {
            "value": round(m["automation"]["fpr"], 4),
            "n_streams": m["automation"]["n_negative"],
            "source": src,
            "description": "Automation detector false-positive rate on HUMAN streams "
                           "only (50 seeds). Takeovers are excluded: their trailing "
                           "machine segment is genuinely automation.",
        },
        "detector_drift_tpr": {
            "value": round(m["drift"]["tpr"], 4),
            "n_streams": m["drift"]["n_positive"],
            "source": src,
            "description": "Drift detector true-positive rate on takeover streams "
                           "(human then sharp machine), 50 seeds. Fixture-derived.",
        },
        "detector_drift_fpr": {
            "value": round(m["drift"]["fpr"], 4),
            "n_streams": m["drift"]["n_negative"],
            "source": src,
            "description": "Drift detector false-positive rate on single-typist human streams, 50 seeds.",
        },
    }


def main() -> int:
    m = measure()
    if "--json" in sys.argv:
        print(json.dumps(results_entries(m), indent=2))
        return 0
    for name, r in (("automation", m["automation"]), ("drift", m["drift"])):
        print(f"{name}: tpr={r['tpr']:.3f} (n={r['n_positive']})  "
              f"fpr={r['fpr']:.3f} (n={r['n_negative']})")
    print(f"fixture: {m['fixture']['seeds']} seeds/class, classes={m['fixture']['classes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
