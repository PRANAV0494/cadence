# CADENCE — Unified Project Plan

**One project, built from `KEYSTROKE_models` + `FINALLL` + `keystroke`.**

---

## The pitch

> CADENCE is a transparent proxy that continuously verifies **who is driving** an already-authenticated
> web session — the enrolled human, a different human, or an automated agent — by checking that the text
> arriving at the server was actually produced by the keystrokes it observed, and that the typing rhythm
> still matches the person who logged in. Any web app gains this with **zero code changes**.

**The threat model in one sentence:** the adversary is *already past login* — same session cookie, same
device, same IP, same browser fingerprint. MFA passed. CAPTCHA passed. Every existing control is a
point-in-time check at the door, and all of them are blind afterwards. That blind window is the project.

---

## The reframe (this is what makes it defensible)

Three obvious questions, each replaced by a version you can actually win:

| Obvious framing | Why it loses | Use instead |
|---|---|---|
| "Is this a human or an AI agent?" | Open-world arms race. A tuned `pressSequentially(delay=...)` beats it. | **"Was the text the server received actually produced by the keystrokes we observed?"** — a *verification* question with a deterministic core. |
| "Is this the enrolled human?" | That's a login-time question your password already answered. Cross-session keystroke EER is dominated by device/posture/day variance. | **"Has the driver changed *since login*?"** — within-session change detection kills the dominant nuisance variance. |
| "Is the session malicious?" | Currently answered by feeding invented flow features to a model trained on real ones. | Real HTTP-layer signatures + CICIDS2017 fed **genuine** CICFlowMeter flows. |

Add a fourth state your framing omits, which is the actual 2026 case: **agent-assisted human** (human
logs in, works normally, then delegates a form to an agent). A three-state system misclassifies it.

**The load-bearing design decision:** reconciliation happens **server-side at the proxy**, not in the
injected JavaScript. The proxy sees both the telemetry stream *and* the form POST. An adversary who
patches or suppresses the in-page SDK produces a submission with no supporting keystrokes — which is
itself the detection. To evade, an agent must forge a telemetry stream *consistent with the payload it
submits*, which forces it into the timing model. This is the difference between a browser-side toy and
a system with a real threat model.

---

## Architecture

```
Unmodified web app ◄─────────────────────────────┐
        ▲                                        │
        │ (traffic passes through untouched)     │
┌───────┴────────────────────────────────────────┴────────┐
│ cadence-edge        mitmproxy addon (Python 3)          │
│  • injects cadence-sdk.js into text/html responses      │
│  • CSP-aware (nonce injection), idempotent              │
│  • SERVER-SIDE RECONCILIATION: compares POST body       │
│    against the telemetry stream for that field          │
│  • enforces: 401 + WWW-Authenticate (RFC 9470) | block  │
└───────┬─────────────────────────────────────────────────┘
        │ telemetry (batched, sendBeacon)     ▲ verdict
        ▼                                     │
┌─────────────────────────────────────────────┴───────────┐
│ cadence-core (FastAPI)                                  │
│  features/   ONE extractor, shared offline + online      │
│  detectors/                                              │
│    P  provenance reconciler       (deterministic)        │
│    A  automation likelihood       (GBM on timing+prov)   │
│    I  identity drift              (per-user + changepoint)│
│    M  malice (HTTP sigs + CICIDS2017 on real flows)      │
│  fusion/     sequential log-LR accumulator (SPRT)        │
│  policy/     RFC 9470 challenge · CAEP event emitter     │
└───────┬──────────────────────────────────────┬──────────┘
        │                                      │
   cadence-console (WS)            cadence-flowtap (sidecar)
   timeline · per-detector        tcpdump → CICFlowMeter →
   contribution · decision log    genuine 79-feature flows
```

### Fusion: replace the hand-tuned weights

`FINALLL/app/fusion_engine.py` currently does `0.4·behavioral + 0.6·network` with streak bonuses.
Every constant is indefensible under questioning. Replace with **calibrated sequential evidence**:

Each detector *k* emits a calibrated log-likelihood ratio ℓₖ(t) (Platt/isotonic on held-out data, so
the numbers are real probabilities). Evidence accumulates with decay:

    S(t) = Σₖ Σ_{τ≤t} λ^(t−τ) · ℓₖ(τ)
    Wald bounds:  A = log((1−β)/α),  B = log(β/(1−α))
    S ≥ A → step-up.   S ≤ B → reset to clean.

Three wins: every constant derives from a target error rate instead of being chosen; the friction
budget (α) becomes an explicit dial; and your headline metric becomes **time-to-detect — median
keystrokes until S crosses A** — which is what makes this *continuous* rather than a classifier
with extra steps.

---

## Where your existing code goes

### REUSE (port with light edits)

| From | Into | Why |
|---|---|---|
| `keystroke/backend/app/features.py` | `cadence/features/keystroke.py` | Your best single artifact — 34 features, pure stdlib. Becomes the *one* extractor for offline + online, killing the train/serve skew you have across three implementations. |
| `keystroke/backend/{template.yaml, db.py, auth.py, main.py}` | `cadence/deploy/`, `cadence/api/` | Working SAM + DynamoDB + Mangum + JWT. Real deployed infra beats most students' entire project. |
| `FINALLL/models/keystroke/user_models/` (51 CMU) + `freeform_user_models/` (99 KeyRecs) | `cadence/models/identity/` | 150 trained per-user models — the cross-session identity baseline. |
| `FINALLL/dashboard/` + WS `ConnectionManager` | `cadence/console/` | Sound broadcast pattern; rebuild UI around the timeline. |
| `KEYSTROKE_models/final_models/cicids2017_*` | `cadence/models/network/` | **The orphan worth rescuing** — CPU XGBoost + sklearn scaler that actually loads. `ModelManager` never uses it; it reaches for the cuML copy that needs a GPU. |
| `KEYSTROKE_models/bot/self_awareness.py` | `cadence/ops/health.py` | Rolling metrics + drift detection. Rare in student projects. |
| `KEYSTROKE_models/tests/` | `tests/` | The only tests in any of the three folders. |

### REWRITE

| What | Why |
|---|---|
| `FINALLL/burp_extension.py` | Jython/Python 2, can't share code with sklearn, **and it's broken** (`SDK_URL` line 82, `SDK_INJECT_TAG` lines 123/126 are undefined → `NameError` on load). Keep the idea; discard the code. → mitmproxy addon. |
| `feature_extractor.py::extract_network_features` | Fabricates a 79-dim CICIDS vector from HTTP metadata with hardcoded constants. Model receives garbage. → real CICFlowMeter flows. |
| `feature_extractor.py::extract_attack_signatures` | **The `Accept: */*` bug.** Lines 62-64 fold headers into the scanned string; line 21 pattern `(--|#|/\*)` matches `*/*`. Every browser request → "SQL injection". → scan URL + body only, with a unit test per pattern including negative cases. |
| `keystroke/frontend/public/js/capture.js` | **The dwell bug — see below.** |
| `FINALLL/app/fusion_engine.py` | Hand-tuned constants → sequential log-LR. |
| `FINALLL/evaluation/evaluate_bot.py` | `passed=True` on HTTP 200 *or* 403 → measures "the API answered", not correctness. → labelled ground-truth harness. |

### DROP from the live system (keep as a thesis chapter)

**BETH, Bot-IoT, CTU-13, IoT-23, UNSW-NB15.** Be blunt about why: BETH is eBPF kernel telemetry,
Bot-IoT and IoT-23 are IoT netflow, CTU-13 is botnet netflow. **None describe a browser talking HTTPS
to a web app.** There is no honest way to score web session traffic with them.

They can't ship anyway: 4 of 6 scalers are **cuML** and fail on any CPU machine; **UNSW-NB15's saved
feature list is corrupt** (~119 of 160 "names" are data values read as a header row); CTU-13's "93.6%
accuracy" hides botnet-class F1 of **0.417**; IoT-23's label encoder contains leaked Zeek UIDs as class
names.

---

## Two bugs that must be fixed first (both verified in your data)

### 1. The dwell-time bug — this invalidates your headline ML result

`capture.js` records `key_index: typingInput.selectionStart`. On keydown the caret sits *before* the
inserted character; on keyup, *after*. So `features.py::_parse_events`, which matches keydown to keyup
by `key_index`, pairs every keydown with the **previous** character's keyup.

**Measured directly from `keystroke_export_20260513.csv`:**

| Group | n | median mean_dwell | % negative |
|---|---|---|---|
| human | 293 | **−285.5 ms** | **85.0%** |
| bot_synthetic | 300 | +67.9 ms | 0.0% |

Dwell time is physically impossible to be negative. The two classes are perfectly separable by
`dwell < 0`, which is why the classifier scores 1.0/1.0. **Your headline ML result is a measurement
of a bug**, not of bot detection.

*Consequences:* 11 of 28 model input columns are corrupt (all six distribution features,
mean/std dwell, coefficient of variation, rolling window variance, per-key flight times).
`docs/feature_verification.md:29` marks this logic "✅ Correct" — it audited the Python in isolation and
never checked what `key_index` contains at runtime. That's a good thesis paragraph on why unit tests
that don't cross the client/server boundary miss integration bugs.

*Fix:* key events by `e.code` + a monotonic press counter, never by caret position.
*Salvage:* everything from keydown timestamps alone is fine — inter-key latencies, WPM (median 31.4,
plausible), digraph, pause, and error features. Dwell needs re-collection.

### 2. The fabricated t-test — ALREADY FIXED on your GitHub profile

`Advanced_Keystroke_Dynamics_Authentication.ipynb` cell 20:

```python
iso_eers = results_df['EER'].values
svm_eers = iso_eers * 1.1          # placeholder for comparison
t_stat, p_val = ttest_rel(iso_eers, svm_eers)   # → <!--!retracted-->4.689e-21<!--/-->
```

That t-tests a vector against itself scaled by 1.1. The p-value is arithmetic, not evidence.
**The real test** is in `Final_Keystroke_Dynamics_Full.ipynb` cell 13: IF vs OCSVM,
**t = 3.1127, p = 0.0031** — a perfectly respectable result. Use that one everywhere.
Also drop "vs 0.51 global model": EER 0.5065 is chance, so beating it is not a finding.

---

## Honest novelty assessment (ranked)

**1. Server-side input-provenance reconciliation — genuinely novel framing.** Bot vendors check "did we
see events"; nobody publishes the reconciliation formulation (replay the event log, compare to what the
server received, at the proxy where the adversary can't patch it). *Caveat:* an agent using
`pressSequentially()` reconciles perfectly. This raises the floor; it doesn't close the door. Measure it
as "% of off-the-shelf agent frameworks caught with the timing model disabled."

**2. Mid-session driver-handoff detection via change-point detection — strong and testable.** arXiv
returns zero for change-point + continuous authentication + session. The falsifiable hypothesis: a
within-session reference window eliminates device/keyboard/posture/day variance — the dominant error
sources — so handoff detection should beat cross-session verification EER on the same subjects.

**3. A human↔agent handoff dataset with real 2026 agent frameworks — highest value per hour.**
Nearest prior work (Fayolle et al., arXiv 2606.30119) fingerprints agents at network/HTTP/browser
layers. Yours is temporal and fingerprint-independent, and answers what theirs cannot: *is this still
the person who logged in?*

**4. Keystroke dynamics under browser timer clamping — small, cheap, unexamined.** The literature uses
lab-grade timings; deployed systems get Firefox's 2 ms clamp, Chrome's ~100 µs, 100 ms under
`resistFingerprinting`. Quantize CMU data at each level, report the EER curve. Two days' work, a real
ablation, and it justifies your deployment choices.

**5. Zero-integration proxy deployment — useful engineering, NOT novel research.** It's patented
(**US 12,143,396 B2** describes a risk-assessment proxy injecting behavioral-biometric collection into
apps that "cannot be updated") and shipped by Cloudflare and Akamai. Claim **"first open-source
implementation"**, never "novel idea".

**6. Calibrated sequential fusion — necessary, not novel.** Wald's SPRT is from 1945. Its value is
making the system *evaluable*.

**7. Per-user keystroke models — not novel, and currently below baseline.** Your best CMU result is
LOF at 0.1367. Killourhy & Maxion (DSN 2009), on *the same 51 subjects and the same CSV you have*,
report scaled Manhattan at **0.0962**. You are ~40% worse than a 2009 baseline. Report as a
reproduction with a known gap, never as a result.

**8. The 6-dataset IDS zoo and "SHAP explanations" — zero novelty, and the SHAP claim isn't true.**
There is no SHAP in any `.py` file. `ModelManager.explain_prediction()` uses
`feature_importances_ × raw values`, which is not SHAP. Wire real SHAP in or stop calling it SHAP.

### What the prior-art sweep actually found

- **No paper fuses keystroke dynamics with network telemetry into a unified risk score.** Five sweeps
  across arXiv, OpenAlex, DBLP. The reason isn't brilliance — it's that **no dataset has both streams
  from one population**, except **TWOS** (Harilal et al., MIST@CCS 2017: keyboard + mouse + process +
  network from 24 users, labelled masquerader/traitor scenarios). Nobody has used its full multimodality.
- **The one real competitor:** Mohamed & Arabo, *Electronics* 2026, 15(1):248 — fuses CERT logs with
  Balabit **mouse** dynamics, 1D-CNNs, Splunk. Its flaws are your differentiators: mouse not keystroke;
  **stitches two unrelated populations**; no risk-scoring/step-up layer.
- **The finding you must engage with:** Giovanini et al. (arXiv 2105.09900) combined process, network,
  mouse and keystroke events from 31 users — and found **95.69% of top discriminative features were
  network-related.** The honest hypothesis to test is whether keystroke adds anything over network
  features. A well-executed negative result is publishable.
- **Open source: the gap is real and verified.** The entire keystroke-biometrics category on GitHub
  tops out at **41 stars** (dead since 2018); ~70% are notebooks against CMU. The best OSS risk engine,
  **tirreno** (1,503★), has *zero* behavioral biometrics. Every vendor open-sources the capture layer
  and hides the scorer (TypingDNA ships recorders, scoring is a closed API call). **Shipping the scorer
  is the actual contribution.**
- **Agent detection got crowded in mid-2026** — six papers in a ten-week window (FP-Agent, Whose Agent
  Are You?, Broken Gates, etc.). The window on *"can we detect agents at all?"* is largely closed. But
  every one of those results rests on **browser-automation artifacts** (Playwright/CDP synthesized
  events) which are fixable defects, not invariants. *"What survives adversarial humanization?"* is open.
- **Adversarial robustness is the cleanest open problem.** Attack literature is far ahead of defense:
  Negi et al. (NDSS 2018) compromise 40–70% of users in ten tries; Van Hamme et al. (EuroS&P 2023) find
  keystroke dynamics ~20× weaker than a password and argue in IEEE TIFS 2024 that **FMR is an inadequate
  security metric**. The KVC challenge has **no adversarial track**. No ASVspoof-equivalent benchmark of
  attacked keystroke samples exists.

**The strongest overall framing:** risk-based auth (sparse) × biometric+telemetry fusion (near-empty)
**evaluated under an adversarial threat model rather than on accuracy.** Each area alone is saturated
or vendor hype; the intersection under adversarial evaluation is where the whitespace is.

---

## The 90-second demo

Split screen: unmodified web app left, CADENCE console right. One take, no cuts.

| t | Beat |
|---|---|
| 0–10 s | Show the app's source. `grep -r cadence .` → zero matches. Start proxy. Reload. SDK is in the DOM. **Zero code changes, proven in ten seconds.** |
| 10–25 s | Log in, start a funds-transfer form. Console: `driver = enrolled_human`, evidence trending negative, green. |
| 25–50 s | **The money shot.** Walk away. A `browser-use` agent takes over *the same browser* — same cookies, same session token, same TLS fingerprint, same IP, same canvas hash. Every conventional defense sees zero change. Agent fills the payee field. Console: `PROVENANCE MISMATCH: 24 characters present, 0 keystrokes observed`. `401 WWW-Authenticate`. Transfer blocked. |
| 50–70 s | Restart. Agent now types character-by-character with randomized delays — provenance reconciles cleanly, mismatch detector silent. The **timing** model carries it. Caption: **"keystrokes to detect: 41."** This beat separates you from a demo that only catches `fill()`. |
| 70–85 s | A *different human* sits down. Automation signals clean; identity drift alone diverges → `driver = other_human` → step-up. Three outcomes, one system. |
| 85–90 s | Timeline with per-detector contribution stacked. |

On-screen once: **same session, same cookies, same device, same IP, same fingerprint.** MFA passed.
CAPTCHA passed. Every existing control is blind here by construction. Yours is not.

---

## Build plan

**Already done (~40%):** the 34-feature extractor · a live AWS deployment with real participants ·
150 per-user identity models · proxy injection as a design · the CICIDS2017 CPU model · a WS
dashboard · `self_awareness.py` · the only test suite.

| Phase | Time | Deliverable |
|---|---|---|
| W1 | Weekend | Rotate secrets, pseudonymise PII, `git init` one monorepo. Port Burp → mitmproxy addon that actually injects. Unify the three extractors. |
| W2 | Weekend | Kill the HTTP-status oracle. Labelled session harness + metrics (EER, DR@budget, time-to-detect). Re-run everything; publish corrected numbers. |
| W3 | Weekend | Fix `capture.js`; redeploy; re-collect ~20 clean sessions to confirm dwell is positive. Timer-clamping ablation. |
| M1 | Month | **The dataset.** Drive your own app with 6+ agent frameworks × input modes, plus ~30 human sessions including scripted handoffs (human types 60 s → agent takes over mid-form). Strongest contribution; don't compress it. |
| M2 | Month | Provenance reconciler (server-side). Automation detector retrained on M1. **Leave-one-agent-out** evaluation — train on five frameworks, test on the sixth. That's the only number that predicts field performance. |
| M3 | Month | Change-point handoff detector + sequential log-LR fusion. Time-to-detect curves. Per-detector ablation. |
| M4 | Month | Adversarial round: agents tuned to mimic your enrolled user's timing; replay attacks; statistical forgery; cGAN presentation attack. **Report where you break** — that section will be the most credible thing in the thesis. |
| M5 | Month | RFC 9470 + CAEP standards layer. `cadence-flowtap` with real CICFlowMeter. Console. Latency/overhead benchmarks. |
| M6 | Month | Write-up, demo video, repo polish, ablation table. |

*M1 will overrun.* Protect it by cutting M5's flowtap first — the network branch is the least novel
part and the thesis survives without it.

---

## Do not claim

- ❌ "Trained on 136 million keystrokes" → "a 10,000-participant subset of the Aalto corpus (~7.3M keystrokes)"
- ❌ "State-of-the-art keystroke authentication" — you're 40% behind a 2009 baseline on CMU
- ❌ "p = <!--!retracted-->4.7e-21<!--/-->" — artifact of `iso_eers * 1.1`
- ❌ "100% bot detection accuracy" — separable by construction, plus the dwell bug
- ❌ "SHAP-explained predictions" — until SHAP is actually in the inference path
- ❌ "Detects AI agents" → "detects unattested input provenance and behavioral discontinuity; evaluated against N agent frameworks with leave-one-out generalisation of X%"
- ❌ "Novel intrusion detection" — XGBoost + SMOTE on CICIDS2017 is the hello-world of ML security
- ❌ "Production-ready" / "zero-trust compliant" → "research prototype, deployed and evaluated"
- ❌ Any claim of unspoofability. The SDK runs in the adversary's DOM. Saying this **increases** credibility.

---

## Repo structure

```
cadence/
├── README.md                    ← demo GIF above the fold; threat model in ¶1
├── pyproject.toml               ← ONE lockfile. Pin sklearn or your .joblib files won't load.
├── cadence/
│   ├── features/keystroke.py    ← the shared extractor (train == serve)
│   ├── detectors/{provenance,automation,identity,malice}.py
│   ├── fusion/sequential.py
│   ├── policy/{rfc9470.py,caep.py}
│   └── api/
├── edge/                        ← mitmproxy addon + cadence-sdk.js
├── console/
├── training/                    ← headless CLIs, no notebooks in the critical path
├── evaluation/
│   ├── harness/                 ← agent drivers, session replay
│   └── metrics.py               ← EER, DR@budget, time-to-detect, bootstrap CIs
├── datasets/README.md           ← download scripts + checksums, NOT the data
├── models/                      ← small artifacts only; >50 MB via Releases/DVC
├── deploy/                      ← SAM template, secrets via SSM
├── docs/{THREAT_MODEL,EVALUATION,LIMITATIONS,ETHICS}.md
└── tests/
```

**README must contain, in this order:** (1) the 90-second demo GIF above the fold; (2) one paragraph
stating the threat model precisely; (3) a results table **with confidence intervals and sample counts
in every row**; (4) **a baseline row you lose to** — scaled Manhattan 0.0962 next to your 0.1367;
(5) a **Limitations section placed above Installation** (placement is the signal); (6) the
leave-one-agent-out number as the headline, not in-distribution accuracy; (7) exact reproduction
commands with pinned deps and seeds; (8) ethics/consent statement; (9) a prior-art table with a
"what CADENCE does differently" column; (10) what this is **not**.

`.gitignore` must cover `__pycache__/`, `.pytest_cache/`, `lambda_package/`, `packages/`,
`deploy-full.zip`, `checkpoints/`, and the raw participant CSV.

---

## Blockers to clear before any of this becomes a git repo

1. **Rotate the JWT secret and admin password.** `keystroke/backend/app/auth.py` and `template.yaml`
   default `JwtSecretKey` to `"change-me-in-production-use-a-long-random-string"` — and it's a
   CloudFormation *parameter default*, so `sam deploy` without an override ships it as the production
   signing key. Anyone can mint admin JWTs for your live API. The plaintext password is in
   `docs/PROJECT_DOCUMENTATION.md` (lines ~19-20, 498, 719) and in an `auth.py` comment.
2. **Delete `FINALLL/security_logs.json`** — 2.2 MB of your real browsing history, including Google
   autocomplete captured keystroke-by-keystroke.
3. **Pseudonymise `keystroke_export_20260513.csv`** — real first-and-last names of 49 participants,
   unencrypted, in a OneDrive-synced folder with no backup. Keep the mapping out of the repo, and write
   the consent/ethics note you'll need for the thesis anyway.
