# What was copied here, and from where

Source folders are **untouched** — everything here is a copy. 13 MB total (vs ~2.1 GB of source).

## Kept — reuse as-is or with light edits

| Here | From | Why |
|---|---|---|
| `cadence/features/keystroke.py` | `keystroke/backend/app/features.py` | The 34-feature, pure-stdlib extractor. Becomes the **one** extractor for offline + online, killing the train/serve skew across three implementations. |
| `cadence/api/{main,db,auth,models,csv_export,phrases_db}.py` | `keystroke/backend/app/` | Working FastAPI + Mangum + DynamoDB + JWT layer. |
| `cadence/ops/health.py` | `KEYSTROKE_models/bot/self_awareness.py` | Rolling metrics + confidence-drift detection. |
| `deploy/{template.yaml,samconfig.toml,requirements.txt}` | `keystroke/backend/` | Real, working SAM deployment. |
| `models/network/cicids2017_*` (590 KB) | `KEYSTROKE_models/final_models/` | **The orphan worth rescuing** — the only CPU-loadable network model. `ModelManager` never used it; it reached for the cuML copy that needs a GPU. |
| `models/automation/` | `keystroke/human_vs_bot_model_artifacts/` | RF pipeline + training report + plots. **Result is invalid — see below.** |
| `console/{index.html,keystroke.html,dashboard.js}` | `FINALLL/dashboard/`, `keystroke/frontend/` | UI to rebuild around the timeline. |
| `training/` | `FINALLL`, `keystroke` roots | Training + synthetic-bot generation scripts. |
| `tests/` | `KEYSTROKE_models/tests/` | The only tests in any of the three folders. |
| `notebooks/exploration/` | all three | The 4 notebooks with real executed output. **Non-authoritative** — results move to `evaluation/`. |
| `data/DSL-StrongPasswordData.csv` | `FINALLL/` | CMU benchmark, 51 subjects. Gitignored — add a download script. |

## Kept as reference only — these get rewritten

| Here | Why it's reference, not code |
|---|---|
| `edge/reference/burp_extension.py` | Jython/Python 2, and **broken on load** — `SDK_URL` (line 82) and `SDK_INJECT_TAG` (lines 123/126) are never defined → `NameError`. Good idea, discard the implementation. → mitmproxy addon in `edge/`. |
| `edge/reference/capture.js.BUGGY` | Renamed deliberately. Keys events by `selectionStart`, so keydown pairs with the **previous** character's keyup. → rewrite as `edge/cadence-sdk.js`. |
| `edge/reference/keystroke_sdk.js` | The SDK the Burp extension injected — structure to port. |
| `reference/legacy_app/feature_extractor.py` | `extract_network_features()` fabricates 79 CICIDS features from HTTP metadata with hardcoded constants. `extract_attack_signatures()` folds headers into the scan string, so pattern `(--\|#\|/\*)` matches `Accept: */*` → every browser request flagged as SQL injection. |
| `reference/legacy_app/fusion_engine.py` | `0.4·behavioral + 0.6·network` hand-tuned constants → replace with calibrated sequential log-LR (SPRT). |
| `evaluation/reference/evaluate_bot.py` | Sets `passed=True` on HTTP 200 **or** 403 — measures "the API answered", not correctness. Hence 23/23. |
| `reference/model_manager.py`, `risk_engine.py` | Inference + risk logic to port selectively. |

## Deliberately NOT copied

| What | Size | Why |
|---|---|---|
| 153 per-user `.pkl` models | **224 MB** | Regenerable in **13.86 s** (your own notebook output). Copied the `*_metadata.json` instead — those hold each user's EER and threshold. |
| BETH / Bot-IoT / CTU-13 / IoT-23 / UNSW-NB15 models | ~350 MB | Wrong data domain — eBPF kernel telemetry and IoT netflow don't describe a browser talking HTTPS to a web app. Also 4 of 6 scalers are cuML (fail on CPU), and UNSW-NB15's saved feature list is corrupt (~119 of 160 "names" are data values). |
| `FINALLL/security_logs.json` | 2.2 MB | **Your real browsing history**, including Google autocomplete captured keystroke-by-keystroke. |
| `checkpoints/` | 1.3 GB | Regenerable intermediates. |
| `lambda_package/`, `packages/`, `deploy-full.zip`, `.aws-sam/` | ~165 MB | Two duplicate vendored dependency trees + build output. |
| `attack_mapper.py`, `attack_logger.py`, `risk_calculator.py`, `debug_*.py` | — | Never imported, or duplicate logic that disagrees with `risk_engine.py`. |

## Security changes made during the copy

1. **`cadence/api/auth.py`** — the insecure default is gone. `SECRET_KEY` now reads `os.environ["JWT_SECRET_KEY"]` and **fails fast if unset** instead of silently signing with `"change-me-in-production..."`. The comment containing the plaintext password was deleted.
2. **`deploy/template.yaml`** — removed the `Default:` values for `JwtSecretKey`, `AdminUsername`, and `AdminPasswordHash`. They were CloudFormation *parameter defaults*, so `sam deploy` without an override shipped them as the production signing key. Now the deploy fails unless you pass real values.
3. **`.gitignore`** covers `data/private/`, all `*.pkl`/`*.joblib` (except the two small network models), datasets, and build junk.

> **Still on you:** the original folders are unchanged, so those secrets are still in
> `keystroke/backend/app/auth.py`, `keystroke/backend/template.yaml`, and
> `keystroke/docs/PROJECT_DOCUMENTATION.md` (lines ~19-20, 498, 719). **Rotate the actual password and
> JWT secret on the live deployment** — scrubbing a copy doesn't undo a key that's already public.

## Data that needs handling before any commit

`data/private/keystroke_export_20260513.csv` — 593 rows, real first-and-last names of <!--@participants_collected-->49<!--/--> participants.
Gitignored, but pseudonymise to stable hashes and keep the mapping outside the repo. You need the
consent/ethics note for the thesis anyway.

**Also — this file contains the dwell-time bug.** Verified directly:

| Group | n | median mean_dwell | % negative |
|---|---|---|---|
| human | 293 | **<!--@legacy_export_median_dwell_ms-->−285.5<!--/--> ms** | **<!--@legacy_export_negative_dwell_fraction-->85.0%<!--/-->** |
| bot_synthetic | 300 | +67.9 ms | 0.0% |

Dwell time can't be negative. The two classes separate perfectly on `dwell < 0`, which is why the
classifier scores 1.0/1.0. **Everything in `models/automation/` is a measurement of that bug.**
Salvageable: anything derived from keydown timestamps alone (inter-key latency, WPM, digraph, pause,
error features). Dwell needs re-collection after fixing `capture.js`.
