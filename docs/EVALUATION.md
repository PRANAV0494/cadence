# Evaluation

Numbers quoted in markdown must exist in `evaluation/results.json` with a
source, or CI fails (`evaluation/check_docs.py`).

**What is measured today**

- Detector rates on a labelled *synthetic* fixture (`calibrate_detectors.py`).
  Those rates are easy (pause-free machines); field rates will be worse.
- CMU identity EER vs Killourhy & Maxion 2009 — this work is behind that
  baseline; the README states the gap.

**What is not a field result**

- `evaluation/harness/streams.py` — labelled synthetic JSONL for
  `cadence eval`. Not a substitute for agent-framework captures.
- `evaluation/timer_clamp.py` — timestamp quantization only; it does not
  invent an EER.

**Still outstanding (not in this repo yet)**

- Recapture of human sessions after the dwell-bug SDK fix.
- Leave-one-agent-out on real 2026 agent frameworks.
- Adversarial humanization / statistical forgery round.
