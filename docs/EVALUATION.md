# Evaluation

Marked claims — numbers wrapped in an HTML-comment span naming a
`results.json` key — must match `evaluation/results.json` at the shown
precision, or CI fails (`evaluation/check_docs.py`); the checker also
rejects a short denylist of retracted literals. Unmarked numerals are
**not** gated — the marker is what buys the guarantee.

**What is measured today**

- Detector rates on a labelled *synthetic* fixture (`calibrate_detectors.py`).
  Those rates are easy (pause-free machines); field rates will be worse.
- CMU identity EER vs Killourhy & Maxion 2009 — this work is behind that
  baseline; the README states the gap.

**What is not a field result**

- `cadence eval <session.jsonl>` (`cadence/eval.py`) replays exactly what
  it is given and invents nothing; leave-one-agent-out waits for real
  agent captures.
- `evaluation/harness/streams.py` — labelled synthetic JSONL (jittered
  human, constant machine, untrusted script, handoff). Fixtures for
  `cadence eval`, not a substitute for agent-framework captures.
- `evaluation/timer_clamp.py` — timestamp quantization onto browser
  grids only. It does not invent an EER.

**Still outstanding**

- Recapture of human sessions after the dwell-bug SDK fix
  (`docs/RECAPTURE.md`).
- Leave-one-agent-out on real 2026 agent frameworks.
- Adversarial humanization / statistical forgery round.
