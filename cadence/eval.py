"""cadence eval: replay a saved session through detectors + fusion.

Input: a JSONL file where each line is either a bare event dict (the
SDK's wire format) or {"events": [...]} (a flushed beacon as buffered
by the proxy). Events are replayed in file order, preserving flush
boundaries, exactly as _accumulate would see them.

Output: the fusion decision at each round, the terminal decision, and
time-to-detect — milliseconds from the first event of the session to
the first event of the round where the walk crossed a terminal bound.
Leave-one-agent-out waits for real agent captures; this replays what
is given, honestly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "edge"))

from automation import is_automated  # noqa: E402
from drift import drift_signal  # noqa: E402
from fusion import bounds, update  # noqa: E402


def _rounds(lines: list[str]) -> list[list[dict]]:
    """Each line becomes one replay round (beacon boundary preserved)."""
    rounds: list[list[dict]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue  # malformed line: skip, do not crash the replay
        if isinstance(payload, dict) and "events" in payload:
            events = payload["events"] or []
        elif isinstance(payload, dict):
            events = [payload]
        else:
            continue
        if events:
            rounds.append(events)
    return rounds


def replay(rounds: list[list[dict]]) -> dict:
    """Run the walk over replay rounds. Returns decisions and timing."""
    lo, hi = bounds()
    llr = 0.0
    decision = "continue"
    last_flags: dict[str, object] = {}
    first_ts = None
    detect_ts = None
    history: list[dict] = []

    for i, events in enumerate(rounds):
        round_last_ts = None
        for e in events:
            ts = e.get("timestamp")
            if isinstance(ts, (int, float)):
                if first_ts is None:
                    first_ts = ts
                round_last_ts = ts
        signals = {
            "automation": is_automated([e for r in rounds[: i + 1] for e in r]),
            "drift": (drift_signal([e for r in rounds[: i + 1] for e in r]) or {}).get("drift"),
            "provenance": None,
        }
        fresh = {}
        for name, fired in signals.items():
            if name not in last_flags or last_flags[name] != fired:
                fresh[name] = fired
                last_flags[name] = fired
        state = update(llr, fresh)
        llr = state["llr"]
        decision = state["decision"]
        history.append({"round": i, "llr": round(llr, 3), "decision": decision})
        if decision in ("step-up", "clean"):
            # Terminal rounds timestamp detection. LATER terminal rounds
            # overwrite earlier ones: a session that cleared and was then
            # taken over has its detection time at the takeover crossing,
            # because the walk kept accumulating and reversed. The final
            # decision's moment is the honest "when did we know".
            if round_last_ts is not None:
                detect_ts = round_last_ts
    ttd = None
    if first_ts is not None and detect_ts is not None and any(
        h["decision"] != "continue" for h in history
    ):
        ttd = detect_ts - first_ts
    return {
        "decision": decision,
        "rounds": len(rounds),
        "history": history,
        "time_to_detect_ms": ttd,
        "bounds": {"lower": round(lo, 3), "upper": round(hi, 3)},
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="cadence eval")
    parser.add_argument("session", help="session JSONL file to replay")
    args = parser.parse_args(argv)

    path = Path(args.session)
    if not path.is_file():
        print(f"cadence eval: no such file: {path}", file=sys.stderr)
        return 1
    rounds = _rounds(path.read_text(encoding="utf-8", errors="replace").splitlines())
    if not rounds:
        print("cadence eval: no events found in file", file=sys.stderr)
        return 1
    result = replay(rounds)
    for h in result["history"]:
        print(f"round {h['round']:>3}  llr {h['llr']:>8}  {h['decision']}")
    print(f"decision: {result['decision']}  rounds: {result['rounds']}")
    ttd = result["time_to_detect_ms"]
    print(f"time-to-detect: {'n/a' if ttd is None else f'{ttd:.0f} ms'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
