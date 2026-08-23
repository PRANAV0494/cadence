# CADENCE — working rules

## Git workflow — follow this for every change

1. **Always start from the latest `origin/main`:**
   ```bash
   git fetch origin
   git checkout main && git pull --ff-only origin main
   git checkout -b <type>/<short-description>
   ```
   Branch names: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`.

2. **One PR per unit of work.** Never commit directly to `main`. Each PR should be one
   reviewable thing — "fix dwell-time key matching", not "week 1 changes".

3. **Open a PR** when the work is done:
   ```bash
   git push -u origin <branch>
   gh pr create --fill
   ```

## Commit attribution — important

All commits are authored by **Pranav Maheshwari <pranavm494@gmail.com>**.

- **Do NOT add `Co-Authored-By:` trailers.** No Claude/AI co-author lines in commit messages
  or PR bodies.
- **Do NOT add "Generated with Claude Code" footers** to PRs or commits.
- Write commit messages in plain imperative mood: `fix: match keydown/keyup by press sequence`.

Verify before committing:
```bash
git config user.name   # → Pranav Maheshwari
git config user.email  # → pranavm494@gmail.com
```

## Never commit these

- `data/private/` — real participant data (49 people's names). Gitignored; keep it that way.
- Any secret: JWT keys, AWS credentials, admin password hashes. Config comes from environment
  variables only. `auth.py` intentionally has **no defaults** — it must fail fast if unset.
- Model blobs (`*.pkl`, `*.joblib`) except the two small files in `models/network/`.
  Large artifacts go to GitHub Releases or DVC.
- Third-party datasets (CMU, KeyRecs, Aalto). Ship download scripts with checksums instead.

## What this project is

A transparent proxy that continuously verifies **who is driving an already-authenticated web
session** — the enrolled human, a different human, or an automated agent. It checks that the text
reaching the server was actually produced by the keystrokes it observed, and that typing rhythm
still matches whoever logged in. Any web app gains this with zero code changes.

**Threat model:** the adversary is *already past login* — same session cookie, same device, same IP,
same browser fingerprint. MFA passed, CAPTCHA passed. Every existing control checks once at the door
and is blind afterwards. That blind window is the project.

See `docs/CADENCE_PLAN.md` for the full design, and `MANIFEST.md` for where each file came from.

## Known issues to respect while working

- **`edge/reference/capture.js.BUGGY`** — keys events by `selectionStart`, so every keydown pairs
  with the *previous* character's keyup. Result: 85% of human dwell times are negative (median
  −285.5 ms). Never copy this pattern. Key events by `e.code` + a monotonic press counter.
- **`models/automation/`** — the 1.0/1.0 human-vs-bot result is a measurement of that bug, not a
  real result. Do not cite it.
- **`reference/legacy_app/feature_extractor.py`** — `extract_attack_signatures()` folds HTTP headers
  into the scanned string, so the pattern `(--|#|/\*)` matches `Accept: */*` and flags every browser
  request as SQL injection. `extract_network_features()` fabricates CICIDS flow features from HTTP
  metadata. Both are reference-only; do not import them.
- **`evaluation/reference/evaluate_bot.py`** — sets `passed=True` on HTTP 200 *or* 403, so it
  measures "the API responded", not correctness.

## Claims discipline

This project is evaluated on measurement honesty, not headline numbers.

- Report confidence intervals and sample counts on every result.
- Include baselines you lose to (Killourhy & Maxion 2009 scaled Manhattan: **EER 0.0962** on the same
  51 CMU subjects; our best so far is LOF at **0.1367**).
- Lead with leave-one-agent-out generalisation, never in-distribution accuracy.
- Never claim: "state-of-the-art", "100% accuracy", "unspoofable", "production-ready",
  "detects AI agents" (say: "detects unattested input provenance and behavioural discontinuity").
