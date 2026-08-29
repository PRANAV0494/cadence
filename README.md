# CADENCE

**Continuous attestation of *who is driving* an authenticated web session.**

> ⚠️ **Status: early research prototype, under active development.** Nothing here is production
> ready, and the numbers below are baselines being re-measured — see [Honest status](#honest-status).

---

## The problem

Every authentication control fires **once, at the door**. Passwords, MFA, CAPTCHA, device
fingerprinting, IP reputation, Web Bot Auth — all of them verify at login and then go quiet.

So consider an adversary who is *already past login*: same session cookie, same device, same IP,
same browser fingerprint, same TLS fingerprint. A hijacked session. A shared workstation. Or — the
2026 case — an AI agent that takes over the browser a human already authenticated.

Every one of those controls sees **nothing change**. That blind window is what CADENCE addresses.

## The approach

CADENCE runs as a transparent proxy in front of an unmodified web app and continuously asks three
questions about whoever is currently driving the session:

| Detector | Question | Method |
|---|---|---|
| **Provenance** | Was the text the server received actually produced by the keystrokes we observed? | Deterministic reconciliation, **server-side at the proxy** |
| **Identity drift** | Has the driver changed *since login*? | Within-session change-point detection against a per-user baseline |
| **Automation** | Does the input timing look synthesised? | Interval regularity (CV + unique-fraction) on trusted character keydowns |

Evidence from each is combined by a **calibrated sequential log-likelihood-ratio accumulator**
(Wald's SPRT), so thresholds derive from a target error rate rather than hand-tuned weights — and
the headline metric becomes *time-to-detect*: how many keystrokes until the system is confident.

**The load-bearing design decision:** reconciliation happens at the proxy, not in the injected
JavaScript. The proxy sees both the telemetry stream *and* the form POST. An adversary who patches
or suppresses the in-page SDK produces a submission with no supporting keystrokes — which is itself
the detection. To evade, an agent must forge telemetry *consistent with what it submits*, which
forces it into the timing model.

## Architecture

```
Unmodified web app ◄──────────────────────────────┐
        ▲                                         │
        │  (traffic passes through untouched)     │
┌───────┴─────────────────────────────────────────┴───────┐
│  edge/          mitmproxy addon                         │
│   · injects cadence-sdk.js into HTML responses          │
│   · reconciles POST bodies against telemetry            │
│   · enforces step-up via RFC 9470                       │
└───────┬─────────────────────────────────────────────────┘
        │ telemetry                          ▲ verdict
        ▼                                    │
┌────────────────────────────────────────────┴────────────┐
│  cadence/                                               │
│   features/    one extractor, shared train + serve       │
│   detectors/   provenance · identity · automation        │
│   fusion/      sequential log-LR (SPRT)                  │
│   policy/      RFC 9470 challenge · CAEP events          │
└─────────────────────────────────────────────────────────┘
```

## Demo

[90-second recording](docs/demo/cadence-demo.webm) — type → allow, paste → 403,
constant-interval stream → 401, then the live console. Mechanics, not a field TPR.

One command. **Normal browser** — no proxy settings, no special Chrome.

Windows (from the repo):

```powershell
.\start.ps1
```

Anywhere with Python 3.11+:

```bash
pip install -e ".[proxy]"
cadence demo
```

Then open **http://127.0.0.1:8080/** in Chrome / Edge / Firefox the way you
already use it. Console: **http://127.0.0.1:8080/__cadence/console**.
If 8080 is taken (including by VS Code auto-forward): `cadence demo --port 9000`.
Turn off **Remote: Auto Forward Ports** or the editor will steal the port
before mitmdump binds.

`cadence proxy` still exists for the lab forward-proxy path (browser must
be pointed at the proxy, HTTPS needs the mitmproxy CA). You do not need
that to try the demo.

What you should see, and why:

| You do | The proxy does | Why |
|---|---|---|
| Type into the `message` box, submit | Green "allowed" page | The typed string contains the submitted text: provenance justified |
| Paste or script-fill that box without typing, submit | `403` from the proxy, nothing forwarded | Text with zero matching keystrokes is unjustified |
| Type with machine-perfect timing (a script driving key events) | `401` with a step-up challenge, nothing forwarded | The SPRT walk crossed the step-up bound |

No accuracy numbers are quoted here beyond what
[evaluation/results.json](evaluation/results.json) records with its
measurement source; the demo shows mechanics, not performance.

## Honest status

**What works today:** `cadence demo` in a normal browser (provenance 403, automation
401, live console); untrusted keydowns ignored; idle session TTL; CAEP-shaped log
events; lexical malice as a weak SPRT input; Wald SPRT fusion; RFC 9470 step-up;
`cadence eval` replay; synthetic harness streams and timer-clamp quantization
(fixtures, not field rates). Also the 34-feature extractor, a deployed
FastAPI/Lambda/DynamoDB collection backend, per-user identity baselines on <!--@cmu_subjects-->51<!--/--> CMU subjects, and one
CPU-loadable network model that is **not** on the live proxy path.

**Still outstanding:** recapture of humans with the rewritten SDK; leave-one-agent-out
on real 2026 agent frameworks; adversarial humanization. The dwell-bug export is still
bad (<!--@legacy_export_negative_dwell_fraction-->85%<!--/--> of recorded human dwell times are negative); `models/automation/`
measures that bug. The Burp extension still doesn't load — the live edge is mitmproxy.

**Current keystroke baseline, and the one it loses to:**

| Method | Dataset | EER | n |
|---|---|---|---|
| Killourhy & Maxion 2009, scaled Manhattan | CMU DSL-StrongPasswordData | **<!--@cmu_baseline_scaled_manhattan_eer-->0.096<!--/-->** | <!--@cmu_subjects-->51<!--/--> subjects |
| This work — Local Outlier Factor | CMU DSL-StrongPasswordData | <!--@cmu_lof_eer-->0.1367<!--/--> | <!--@cmu_subjects-->51<!--/--> subjects |
| This work — One-Class SVM | CMU DSL-StrongPasswordData | <!--@cmu_ocsvm_eer-->0.1375<!--/--> | <!--@cmu_subjects-->51<!--/--> subjects |
| This work — Isolation Forest | CMU DSL-StrongPasswordData | <!--@cmu_isolation_forest_eer-->0.1532<!--/--> | <!--@cmu_subjects-->51<!--/--> subjects |

One-Class SVM significantly outperforms Isolation Forest (paired *t*-test, t = <!--@cmu_if_vs_ocsvm_t_statistic-->3.11<!--/-->, p = <!--@cmu_if_vs_ocsvm_p_value-->0.003<!--/-->).
We are currently **<!--@cmu_gap_to_baseline_percent-->42%<!--/--> behind a 2009 baseline** — this is a reproduction with a known gap, not a
result.

## Limitations

- The SDK runs in the adversary's DOM and **can be patched**. Server-side reconciliation raises the
  cost of evasion; it does not eliminate the attack.
- An agent that types character-by-character with realistic delays reconciles cleanly — detection
  then depends entirely on the timing model, which is a probabilistic arms race.
- Browser timer clamping (Firefox 2 ms, 100 ms under `resistFingerprinting`) degrades timing
  resolution in ways the academic literature, which uses lab-grade timings, does not account for.
- Keystroke dynamics is a **weak** authenticator on its own — roughly 20× weaker than a password
  (Van Hamme et al., EuroS&P 2023), and vulnerable to statistical forgery and master-key attacks.
  CADENCE treats it as a risk signal that triggers step-up, never as an authentication factor.
- Participant data so far is <!--@participants_collected-->49<!--/--> people. That is small.

## What this is not

Not production software. Not a CAPTCHA replacement. Not an authentication factor. Not unspoofable.
Not a claim that AI agents are reliably detectable in general.

## Repository layout

See [`MANIFEST.md`](MANIFEST.md) for the origin of every file and [`docs/CADENCE_PLAN.md`](docs/)
for the full design and build plan (a Hinglish version is in the same folder).

## License

TBD.
