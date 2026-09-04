"""Gate recapture files: paired character dwells must be mostly positive.

Reads the same JSONL `cadence eval` consumes. Pairs keydown/keyup by `seq`
(the rewritten SDK). Exit 0 only when there are enough pairs, the median
dwell is > 0, and negative pairs are rare.

This is a capture-health check, not an EER.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

MIN_PAIRS = 10
MAX_NEGATIVE_FRACTION = 0.05


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
            events.extend(payload["events"])
        elif isinstance(payload, dict):
            events.append(payload)
    return events


def dwells_ms(events: list[dict]) -> list[float]:
    """Character-producing press dwells, keyed by seq (SDK contract)."""
    downs: dict[object, dict] = {}
    out: list[float] = []
    for e in events:
        if e.get("is_modifier") or e.get("is_paste") or e.get("is_backspace"):
            continue
        et = e.get("event_type")
        seq = e.get("seq")
        if seq is None:
            # Unpaired keyup (capture started mid-press) or a seq-less
            # synthetic event: no down to pair with, and None would collide
            # every such event onto one dict slot.
            continue
        if et == "keydown":
            downs[seq] = e
        elif et == "keyup":
            down = downs.pop(seq, None)
            if down is None:
                continue
            t0, t1 = down.get("timestamp"), e.get("timestamp")
            if isinstance(t0, (int, float)) and isinstance(t1, (int, float)):
                out.append(float(t1) - float(t0))
    return out


def report(path: Path) -> dict:
    values = dwells_ms(load_events(path))
    n = len(values)
    n_neg = sum(1 for d in values if d < 0)
    median = statistics.median(values) if values else None
    frac = (n_neg / n) if n else None
    ok = (
        n >= MIN_PAIRS
        and median is not None
        and median > 0
        and frac is not None
        and frac < MAX_NEGATIVE_FRACTION
    )
    return {
        "n_pairs": n,
        "n_negative": n_neg,
        "negative_fraction": frac,
        "median_ms": median,
        "ok": ok,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python evaluation/check_dwell.py <session.jsonl>", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"check_dwell: no such file: {path}", file=sys.stderr)
        return 1
    r = report(path)
    med = "n/a" if r["median_ms"] is None else f"{r['median_ms']:.1f}"
    frac = "n/a" if r["negative_fraction"] is None else f"{100 * r['negative_fraction']:.1f}%"
    print(
        f"{path.name}: pairs={r['n_pairs']} median_dwell_ms={med} "
        f"negative={r['n_negative']} ({frac}) "
        f"{'PASS' if r['ok'] else 'FAIL'}"
    )
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
