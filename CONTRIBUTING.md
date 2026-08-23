# Contributing

## Development workflow

Every change goes through a pull request. Nothing is committed directly to `main`.

```bash
git fetch origin
git checkout main && git pull --ff-only origin main
git checkout -b <type>/<short-description>
# ... work ...
git push -u origin <branch>
gh pr create --fill
```

Branch prefixes: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`.

Keep each PR to one reviewable change — "fix dwell-time key matching", not "week 1 changes".
Commit messages use plain imperative mood: `fix: match keydown/keyup by press sequence`.

## Never commit

- **`data/private/`** — real participant data. This study collected keystroke timings from
  <!--@participants_collected-->49<!--/--> people under consent; their data does not leave the machine it was collected on.
  Pseudonymise to stable hashes before any analysis leaves this repo, and keep the mapping out
  of version control.
- **Secrets of any kind** — JWT signing keys, AWS credentials, admin password hashes.
  All configuration comes from environment variables. `cadence/api/auth.py` intentionally has
  **no defaults**: it raises on startup if the environment is unset, rather than silently
  falling back to a shared development key.
- **Model blobs** (`*.pkl`, `*.joblib`) — except the two small files under `models/network/`.
  Large artifacts belong in GitHub Releases or DVC. Per-user identity models are excluded
  because they regenerate from the training script in seconds.
- **Third-party datasets** (CMU DSL-StrongPasswordData, KeyRecs, Aalto). Ship download scripts
  with checksums instead; redistributing them is not ours to do.

## Claims discipline

This project is judged on measurement honesty, not headline numbers. A result that cannot survive
an adversarial reading is worse than no result.

- **Report sample counts and confidence intervals on every number.** A table row without an *n*
  is not a result.
- **Include baselines you lose to.** Killourhy & Maxion (2009) report EER **<!--@cmu_baseline_scaled_manhattan_eer-->0.0962<!--/-->** with scaled
  Manhattan distance on the same 51 CMU subjects; our best is currently **<!--@cmu_lof_eer-->0.1367<!--/-->**. That gap is
  stated in the README and stays there until it closes.
- **Lead with out-of-distribution generalisation**, not in-distribution accuracy. For automation
  detection this means leave-one-agent-out: train on N−1 agent frameworks, test on the held-out
  one. In-distribution accuracy predicts nothing about deployment.
- **Evaluation measures predictions, not plumbing.** A test that passes because an HTTP request
  returned 200 is not a test.
- **Phrases that do not appear in this project:** "state-of-the-art", "100% accuracy",
  "unspoofable", "production-ready", "military-grade". We do not claim to "detect AI agents" —
  we detect *unattested input provenance* and *behavioural discontinuity*, evaluated against a
  named, finite set of agent frameworks.

## Known defects — respect these while working

These are documented rather than hidden. Do not import from them, and do not cite their outputs.

| Location | Defect |
|---|---|
| `edge/reference/capture.js.BUGGY` | Keys events by `selectionStart`, which sits before the inserted character on keydown and after it on keyup — so every keydown was matched to the **previous** character's keyup. <!--@legacy_export_negative_dwell_fraction-->85%<!--/--> of recorded human dwell times are negative (median <!--@legacy_export_median_dwell_ms-->−285.5<!--/--> ms). Key events by `e.code` plus a monotonic press counter instead. |
| `models/automation/` | The 1.0 accuracy / 1.0 AUC result is a measurement of the bug above: the classes separate perfectly on `dwell < 0`. Not a real result. |
| `reference/legacy_app/feature_extractor.py` | `extract_attack_signatures()` folds HTTP headers into the scanned string, so the pattern `(--\|#\|/\*)` matches an ordinary `Accept: */*` header and flags every browser request as SQL injection. `extract_network_features()` fabricates CICIDS flow features from HTTP metadata using hardcoded constants, producing out-of-distribution input for a model trained on real packet captures. |
| `evaluation/reference/evaluate_bot.py` | Sets `passed = True` on HTTP 200 *or* 403 — it measures whether the API responded, not whether the prediction was correct. |
| `notebooks/exploration/` | Non-authoritative. Contains a degenerate paired t-test (a vector against itself scaled by 1.1). See that folder's README. |

## Ethics

This system observes typing behaviour. Two rules follow from that:

1. **Consent is not optional.** Any deployment that captures keystroke timing from real users
   requires informed consent covering what is collected, how long it is retained, and how to
   withdraw. Timing data is behavioural biometric data; treat it as sensitive personal data.
2. **The proxy injects a capture SDK into pages passing through it.** That is a capability with
   obvious dual-use risk. It is intended for systems you own or have written authorisation to
   test. Do not deploy it against traffic you do not control.
