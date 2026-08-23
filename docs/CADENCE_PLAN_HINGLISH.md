# CADENCE — Poora Plan (Hinglish)

**Teen folders — `KEYSTROKE_models` + `FINALLL` + `keystroke` — ko milakar ek hi solid project.**

> Ye same document ka Hinglish version hai. Technical terms English mein hi rakhe hain, kyunki
> thesis aur code mein wahi use honge.

---

## Pitch — ek line mein

> CADENCE ek transparent proxy hai jo continuously verify karta hai ki **already logged-in session
> ko chala kaun raha hai** — wahi enrolled human, koi dusra human, ya ek AI agent. Ye check karta hai
> ki server tak jo text pahuncha, wo actually un keystrokes se bana tha jo humne observe kiye —
> aur typing rhythm abhi bhi usi bande se match karta hai jo login kiya tha.
> Kisi bhi web app mein **zero code change** ke saath lag jaata hai.

**Threat model ek line mein:** attacker **pehle hi login kar chuka hai** — same session cookie, same
device, same IP, same browser fingerprint. MFA ho chuka. CAPTCHA ho chuka. Har existing control sirf
darwaaze pe ek baar check karta hai, uske baad andha ho jaata hai. **Wahi blind window hi hamara
project hai.**

---

## Sabse important: framing badalni padegi

Teen obvious sawaal, aur unke jeetne wale versions:

| Obvious sawaal | Kyun haarega | Iski jagah ye poochho |
|---|---|---|
| "Ye human hai ya AI agent?" | Ye open-world arms race hai. Ek tuned `pressSequentially(delay=...)` isko haraa dega. | **"Jo text server ko mila, kya wo sach mein un keystrokes se bana tha jo humne dekhe?"** — ye *verification* ka sawaal hai, iska core deterministic hai. |
| "Ye enrolled human hai?" | Ye to login-time ka sawaal hai, password ne pehle hi answer kar diya. Cross-session keystroke EER mein device/posture/din ka variance haavi rehta hai. | **"Login ke baad se driver badla kya?"** — within-session change detection se wo saara nuisance variance khatam ho jaata hai. |
| "Session malicious hai?" | Abhi ye nakli (fabricated) flow features se answer ho raha hai, jabki model real features pe train hua tha. | Real HTTP-layer signatures + CICIDS2017 ko **genuine** CICFlowMeter flows dena. |

Ek chautha state bhi add karo jo aajkal sabse common hai: **agent-assisted human** — banda khud login
karta hai, thoda kaam karta hai, phir ek form agent ko de deta hai. Teen-state system isko galat
classify karega.

**Sabse important design decision:** reconciliation **server-side proxy pe** hoga, injected JavaScript
mein nahi. Proxy ke paas dono cheezein hoti hain — telemetry stream *aur* form POST. Agar attacker
in-page SDK ko patch ya band kar de, to submission aayega bina supporting keystrokes ke — **aur wahi
detection ban jaata hai**. Bachne ke liye agent ko aisi telemetry banani padegi jo uske submit kiye
payload se *consistent* ho — matlab use majboori mein timing model ke maidan mein aana padega.
Yahi farq hai ek browser-side khilone aur ek real threat model wale system mein.

---

## Architecture

```
Unmodified web app ◄─────────────────────────────┐
        ▲                                        │
        │ (traffic bina chhede paas hota hai)     │
┌───────┴────────────────────────────────────────┴────────┐
│ cadence-edge        mitmproxy addon (Python 3)          │
│  • cadence-sdk.js ko HTML responses mein inject karta   │
│  • CSP-aware (nonce), idempotent                        │
│  • SERVER-SIDE RECONCILIATION: POST body ko us field ki │
│    telemetry stream se compare karta hai                │
│  • enforce: 401 + WWW-Authenticate (RFC 9470) | block   │
└───────┬─────────────────────────────────────────────────┘
        │ telemetry (batched)                 ▲ verdict
        ▼                                     │
┌─────────────────────────────────────────────┴───────────┐
│ cadence-core (FastAPI)                                  │
│  features/   EK hi extractor — offline + online dono     │
│  detectors/                                              │
│    P  provenance reconciler       (deterministic)        │
│    A  automation likelihood       (GBM: timing + prov)   │
│    I  identity drift              (per-user + changepoint)│
│    M  malice (HTTP sigs + CICIDS2017 real flows pe)      │
│  fusion/     sequential log-LR accumulator (SPRT)        │
│  policy/     RFC 9470 challenge · CAEP event emitter     │
└───────┬──────────────────────────────────────┬──────────┘
        │                                      │
   cadence-console (WS)            cadence-flowtap (sidecar)
   timeline · per-detector        tcpdump → CICFlowMeter →
   contribution · decision log    asli 79-feature flows
```

### Fusion: hand-tuned weights hatao

Abhi `FINALLL/app/fusion_engine.py` mein hai `0.4·behavioral + 0.6·network` — plus streak bonuses.
Viva mein koi bhi poochh lega "ye 0.4 aur 0.6 kahan se aaye?" aur koi jawab nahi hoga. Iski jagah
**calibrated sequential evidence** lagao:

Har detector *k* ek calibrated log-likelihood ratio ℓₖ(t) deta hai (Platt/isotonic calibration
held-out data pe, taaki numbers asli probabilities hon). Evidence decay ke saath judta jaata hai:

    S(t) = Σₖ Σ_{τ≤t} λ^(t−τ) · ℓₖ(τ)
    Wald bounds:  A = log((1−β)/α),  B = log(β/(1−α))
    S ≥ A → step-up.   S ≤ B → clean reset.

Teen fayde: har constant target error rate se *derive* hota hai, apne mann se choose nahi karna
padta; friction budget (α) ek explicit knob ban jaata hai; aur tumhara headline metric ban jaata hai
**time-to-detect — median kitne keystrokes mein S threshold cross karta hai**. Yahi cheez isko
"continuous system" banati hai, warna ye bas ek classifier hai.

---

## Tumhara purana code kahan jayega

### REUSE (thoda edit karke uthao)

| Kahan se | Kahan | Kyun |
|---|---|---|
| `keystroke/backend/app/features.py` | `cadence/features/keystroke.py` | Tumhara sabse best artifact — 34 features, pure stdlib. Ye ban jayega *ek hi* extractor offline + online dono ke liye, jisse abhi wala train/serve skew khatam ho jayega (abhi teen alag implementations hain). |
| `keystroke/backend/{template.yaml, db.py, auth.py, main.py}` | `cadence/deploy/`, `cadence/api/` | Chalta hua SAM + DynamoDB + Mangum + JWT. Ek real deployed infrastructure zyadatar students ke poore project se bhaari padti hai. |
| `FINALLL/models/keystroke/user_models/` (51 CMU) + `freeform_user_models/` (99 KeyRecs) | `cadence/models/identity/` | 150 trained per-user models — cross-session identity ka baseline. |
| `FINALLL/dashboard/` + WS `ConnectionManager` | `cadence/console/` | Broadcast pattern sahi hai; UI ko timeline ke around dobara banao. |
| `KEYSTROKE_models/final_models/cicids2017_*` | `cadence/models/network/` | **Ye orphan bachane layak hai** — CPU XGBoost + sklearn scaler jo actually load hota hai. `ModelManager` isko kabhi use hi nahi karta, wo cuML wali copy uthata hai jise GPU chahiye. |
| `KEYSTROKE_models/bot/self_awareness.py` | `cadence/ops/health.py` | Rolling metrics + drift detection. Student projects mein ye rare hai. |
| `KEYSTROKE_models/tests/` | `tests/` | Teeno folders mein sirf yahi tests hain. |

### REWRITE (dobara likhna padega)

| Kya | Kyun |
|---|---|
| `FINALLL/burp_extension.py` | Jython/Python 2 hai, sklearn stack ke saath code share nahi kar sakta, **aur ye toota hua hai** — `SDK_URL` (line 82), `SDK_INJECT_TAG` (lines 123/126) kahin define hi nahi hain, load pe hi `NameError` aayega. Idea achha hai, implementation phenk do. → mitmproxy addon. |
| `feature_extractor.py::extract_network_features` | HTTP metadata se 79-dim CICIDS vector **bana** raha hai hardcoded constants se (`fwd_iat = flow_duration*0.3` type). Model ko kachra mil raha hai. → asli CICFlowMeter flows. |
| `feature_extractor.py::extract_attack_signatures` | **Yahi `Accept: */*` wala bug hai.** Lines 62-64 headers ko scan string mein daal dete hain; line 21 ka pattern `(--\|#\|/\*)` `*/*` se match ho jaata hai. Isliye har normal browser request "SQL injection" ban jaati hai. → sirf URL + body scan karo, aur har pattern ka unit test likho negative cases ke saath. |
| `keystroke/frontend/public/js/capture.js` | **Dwell bug — neeche detail mein.** |
| `FINALLL/app/fusion_engine.py` | Hand-tuned constants → sequential log-LR. |
| `FINALLL/evaluation/evaluate_bot.py` | `passed=True` set karta hai agar HTTP 200 *ya* 403 aaye — matlab ye maapta hai "API ne jawab diya", ye nahi ki "prediction sahi thi". → labelled ground-truth harness. |

### DROP (live system se hatao, thesis mein chapter bana do)

**BETH, Bot-IoT, CTU-13, IoT-23, UNSW-NB15.** Seedhi baat: BETH eBPF kernel telemetry hai, Bot-IoT
aur IoT-23 IoT netflow hain, CTU-13 botnet netflow hai. **Inmein se koi bhi "browser HTTPS pe web app
se baat kar raha hai" ko describe nahi karta.** Web session traffic ko inse score karne ka koi
imaandaar tareeka hai hi nahi.

Waise bhi ye ship nahi ho sakte: 6 mein se 4 scalers **cuML** ke hain, kisi bhi CPU machine pe fail
honge; **UNSW-NB15 ki saved feature list corrupt hai** (160 mein se ~119 "names" actually data values
hain jo header row samajh liye gaye); CTU-13 ka "93.6% accuracy" ke peeche botnet-class F1 sirf
**0.417** hai; IoT-23 ke label encoder mein Zeek connection UIDs class names ban gaye hain.

---

## Do bugs jo sabse pehle theek karne hain (dono maine tumhare data mein verify kiye)

### 1. Dwell-time bug — isse tumhara headline ML result invalid ho jaata hai

`capture.js` mein `key_index: typingInput.selectionStart` record hota hai. Keydown pe caret character
ke *pehle* hota hai, keyup pe *baad* mein. Isliye `features.py::_parse_events`, jo keydown-keyup ko
`key_index` se match karta hai, har keydown ko **pichle** character ke keyup ke saath jod deta hai.

**Seedha `keystroke_export_20260513.csv` se measure kiya:**

| Group | n | median mean_dwell | % negative |
|---|---|---|---|
| human | 293 | **<!--@legacy_export_median_dwell_ms-->−285.5<!--/--> ms** | **<!--@legacy_export_negative_dwell_fraction-->85.0%<!--/-->** |
| bot_synthetic | 300 | +67.9 ms | 0.0% |

Dwell time physically negative ho hi nahi sakta. Dono classes `dwell < 0` se perfectly alag ho jaati
hain — isliye classifier 1.0/1.0 de raha hai. **Tumhara headline ML result bot detection nahi, ek bug
ki measurement hai.**

*Asar:* 28 model input columns mein se 11 corrupt hain (saare six distribution features, mean/std
dwell, coefficient of variation, rolling window variance, per-key flight times).
`docs/feature_verification.md:29` isi logic ko "✅ Correct" bolta hai — usne Python ko akele audit
kiya, ye kabhi check nahi kiya ki runtime pe `key_index` mein aa kya raha hai. Thesis mein iska ek
accha paragraph banta hai: **jo unit tests client/server boundary cross nahi karte, wo integration
bugs nahi pakadte.**

*Fix:* events ko `e.code` + ek monotonic press counter se key karo, caret position se kabhi nahi.
*Bachaav:* jo kuch sirf keydown timestamps se banta hai wo sahi hai — inter-key latencies, WPM
(median 31.4, sahi lagta hai), digraph, pause, error features. Dwell dobara collect karna padega.

### 2. Nakli t-test — GitHub profile pe ye ALREADY THEEK kar diya gaya hai

`Advanced_Keystroke_Dynamics_Authentication.ipynb` cell 20:

```python
iso_eers = results_df['EER'].values
svm_eers = iso_eers * 1.1          # placeholder for comparison
t_stat, p_val = ttest_rel(iso_eers, svm_eers)   # → (retracted — see below)
```

Ye ek vector ka usi vector × 1.1 se t-test kar raha hai. Wo p-value evidence nahi, bas arithmetic hai.
**Asli test** `Final_Keystroke_Dynamics_Full.ipynb` cell 13 mein hai: IF vs OCSVM,
**t = <!--@cmu_if_vs_ocsvm_t_statistic-->3.1127<!--/-->, p = <!--@cmu_if_vs_ocsvm_p_value-->0.0031<!--/-->** — bilkul respectable result. Har jagah wahi use karo.
Aur "vs 0.51 global model" wali baat hata do: EER 0.5065 matlab chance level, usse better hona koi
achievement nahi hai.

---

## Novelty ka imaandaar hisaab (ranked)

**1. Server-side input-provenance reconciliation — sach mein naya framing.** Bot vendors sirf ye
dekhte hain "events dikhe ya nahi"; reconciliation wali formulation koi publish nahi karta (event log
replay karo, server ko jo mila usse compare karo, aur ye proxy pe karo jahan attacker patch nahi kar
sakta). *Caveat:* jo agent `pressSequentially()` use karta hai wo perfectly reconcile ho jayega.
Ye floor upar uthata hai, darwaza band nahi karta. Isko aise measure karo: "timing model band karke
kitne % off-the-shelf agent frameworks pakde gaye."

**2. Mid-session driver-handoff detection (change-point detection se) — strong aur testable.**
arXiv pe change-point + continuous authentication + session pe zero results hain. Testable hypothesis:
within-session reference window device/keyboard/posture/din ka variance hata deta hai — jo keystroke
dynamics ke sabse bade error sources hain — isliye handoff detection ko cross-session verification EER
se better hona chahiye, wahi subjects pe.

**3. Human↔agent handoff dataset, asli 2026 agent frameworks ke saath — sabse zyada value per hour.**
Sabse nazdeek kaam (Fayolle et al., arXiv 2606.30119) agents ko network/HTTP/browser layer pe
fingerprint karta hai. Tumhara approach temporal hai aur fingerprint-independent — aur wo sawaal
answer karta hai jo unka nahi kar sakta: *kya ye abhi bhi wahi banda hai jisne login kiya tha?*

**4. Browser timer clamping ke under keystroke dynamics — chhota, sasta, kisi ne dekha nahi.**
Poori literature lab-grade timings pe chalti hai; deployed systems ko milta hai Firefox ka 2 ms clamp,
Chrome ka ~100 µs, aur `resistFingerprinting` pe 100 ms. CMU data ko har level pe quantize karke EER
curve report karo. Do din ka kaam, ek real ablation, aur ye tumhare deployment choices justify karta hai.

**5. Zero-integration proxy deployment — accha engineering, research novelty NAHI.** Ye **patented**
hai (**US 12,143,396 B2** — ek risk-assessment proxy jo un apps mein behavioral-biometric collection
inject karta hai jo "update nahi ho sakte") aur Cloudflare/Akamai ise ship karte hain.
Claim karo **"first open-source implementation"**, kabhi "novel idea" nahi.

**6. Calibrated sequential fusion — zaroori hai, naya nahi.** Wald ka SPRT 1945 ka hai. Iski value ye
hai ki isse system *evaluable* ban jaata hai.

**7. Per-user keystroke models — naya nahi, aur abhi baseline se neeche hai.** CMU pe tumhara best LOF
<!--@cmu_lof_eer-->0.1367<!--/--> hai. Killourhy & Maxion (DSN 2009), *usi 51 subjects aur usi CSV pe jo tumhare paas hai*,
scaled Manhattan se **<!--@cmu_baseline_scaled_manhattan_eer-->0.0962<!--/-->** report karte hain. Tum 2009 ke baseline se ~40% peeche ho. Isko
reproduction batao known gap ke saath, "result" kabhi mat bolo.

**8. 6-dataset IDS zoo aur "SHAP explanations" — zero novelty, aur SHAP wali baat abhi sach nahi hai.**
Kisi bhi `.py` file mein SHAP hai hi nahi. `ModelManager.explain_prediction()` actually
`feature_importances_ × raw values` karta hai, jo SHAP nahi hai. Ya to asli SHAP inference path mein
lagao, ya use SHAP bolna band karo.

### Prior-art search mein kya nikla

- **Koi paper keystroke dynamics ko network telemetry ke saath fuse karke unified risk score nahi
  banata.** Paanch sweeps arXiv, OpenAlex, DBLP pe. Wajah brilliance nahi hai — wajah ye hai ki
  **kisi public dataset mein dono streams ek hi population se nahi hain**, siwaay **TWOS**
  (Harilal et al., MIST@CCS 2017: keyboard + mouse + process + network, 24 users, labelled
  masquerader/traitor scenarios). Uski full multimodality kisi ne use nahi ki.
- **Ek hi real competitor:** Mohamed & Arabo, *Electronics* 2026, 15(1):248 — CERT logs ko Balabit
  **mouse** dynamics ke saath fuse karta hai. Uski kamzoriyan tumhari differentiators hain: mouse hai
  keystroke nahi; **do bilkul alag populations ko jodta hai**; aur risk-scoring/step-up layer hai hi nahi.
- **Jis finding se ladna padega:** Giovanini et al. (arXiv 2105.09900) ne 31 users se process, network,
  mouse, keystroke events combine kiye — aur paaya ki **95.69% top discriminative features
  network-related the.** Imaandaar experiment yahi hai: kya keystroke network features ke upar kuch add
  bhi karta hai? Aur achhe se kiya gaya **negative result bhi publishable hota hai.**
- **Open source: gap asli hai, verify kiya.** GitHub pe poori keystroke-biometrics category ka top repo
  **41 stars** ka hai (2018 se dead); ~70% notebooks hain CMU pe. Sabse accha open risk engine
  **tirreno** (1,503★) hai — usmein behavioral biometrics **zero** hai. Har vendor *capture* layer
  open-source karta hai aur *scorer* chhupata hai (TypingDNA recorders deta hai, scoring closed API call
  hai). **Scorer ship karna hi asli contribution hai.**
- **Agent detection 2026 ke beech mein bheed ho gaya** — das hafton mein chhe papers (FP-Agent,
  Whose Agent Are You?, Broken Gates, waghera). *"Kya agents detect ho sakte hain?"* wali window
  lagbhag band ho chuki hai. Lekin un sabke results **browser-automation artifacts** pe tike hain
  (Playwright/CDP ke synthesized events) — wo fixable defects hain, invariants nahi.
  *"Adversarial humanization ke baad kya bachta hai?"* — ye abhi khula hai.
- **Adversarial robustness sabse saaf open problem hai.** Attack literature defense se bahut aage hai:
  Negi et al. (NDSS 2018) das koshishon mein 40–70% users compromise kar dete hain; Van Hamme et al.
  (EuroS&P 2023) paate hain ki keystroke dynamics password se ~20× kamzor hai, aur IEEE TIFS 2024 mein
  likhte hain ki **FMR security metric ke liye galat hai**. KVC challenge mein **adversarial track hai
  hi nahi**. Attacked keystroke samples ka koi ASVspoof-jaisa benchmark exist nahi karta.

**Sabse strong overall framing:** risk-based auth (sparse) × biometric+telemetry fusion (lagbhag khaali)
— **aur ise accuracy pe nahi, adversarial threat model pe evaluate karna.** Har area akele saturated
ya vendor-hype hai; intersection pe adversarial evaluation ke saath hi asli whitespace hai.

---

## 90-second demo

Split screen: baayein unmodified web app, daayein CADENCE console. Ek hi take, koi cut nahi.

| t | Kya dikhana hai |
|---|---|
| 0–10 s | App ka source dikhao. `grep -r cadence .` → zero matches. Proxy start karo. Reload. SDK DOM mein hai. **Zero code change, das second mein prove.** |
| 10–25 s | Login karo, funds-transfer form shuru karo. Console: `driver = enrolled_human`, evidence neeche, sab green. |
| 25–50 s | **Asli scene.** Tum uth ke chale jao. Ek `browser-use` agent *usi browser* ko chalane lagta hai — same cookies, same session token, same TLS fingerprint, same IP, same canvas hash. Har conventional defense ko kuch badla hua dikhta hi nahi. Agent payee field bharta hai. Console: `PROVENANCE MISMATCH: 24 characters present, 0 keystrokes observed`. `401 WWW-Authenticate`. Transfer block. |
| 50–70 s | Restart. Ab agent character-by-character randomized delays ke saath type karta hai — provenance clean reconcile ho jaata hai, mismatch detector chup hai. Ab **timing** model kaam karta hai. Caption: **"keystrokes to detect: 41."** Yahi beat tumhe un demos se alag karta hai jo sirf `fill()` pakadte hain. |
| 70–85 s | Ek *dusra human* baith jaata hai. Automation signals clean; sirf identity drift diverge karta hai → `driver = other_human` → step-up. Teen alag outcomes, ek system. |
| 85–90 s | Timeline with per-detector contribution stacked. |

Screen pe ek baar likho: **same session, same cookies, same device, same IP, same fingerprint.**
MFA passed. CAPTCHA passed. Har existing control yahan by-construction andha hai. Tumhara nahi hai.

---

## Build plan

**Pehle se ban chuka (~40%):** 34-feature extractor · live AWS deployment real participants ke saath ·
150 per-user models · proxy injection ka design · wo CICIDS2017 model jo CPU pe load hota hai ·
WS dashboard · `self_awareness.py` · ekmatra test suite.

| Phase | Time | Deliverable |
|---|---|---|
| W1 | Weekend | Secrets rotate, PII pseudonymise, `git init` ek monorepo. Burp → mitmproxy addon port karo jo sach mein inject kare. Teeno extractors ko ek karo. |
| W2 | Weekend | HTTP-status oracle hatao. Labelled session harness + metrics (EER, DR@budget, time-to-detect). Sab dobara chalao; corrected numbers publish karo. |
| W3 | Weekend | `capture.js` fix karo; redeploy; ~20 clean sessions dobara collect karke confirm karo ki dwell positive aa raha hai. Timer-clamping ablation. |
| M1 | Month | **Dataset.** Apni hi app ko 6+ agent frameworks × input modes se chalao, plus ~30 human sessions jismein scripted handoffs hon (human 60 s type kare → agent beech form mein le le). Ye sabse strong contribution hai; ise mat kaato. |
| M2 | Month | Provenance reconciler (server-side). Automation detector M1 pe retrain. **Leave-one-agent-out** evaluation — paanch frameworks pe train, chhathe pe test. Sirf yahi number field performance predict karta hai. |
| M3 | Month | Change-point handoff detector + sequential log-LR fusion. Time-to-detect curves. Per-detector ablation. |
| M4 | Month | Adversarial round: agents jo tumhare enrolled user ki timing distribution copy karein; replay attacks; statistical forgery; cGAN presentation attack. **Jahan tumhara system toote wo report karo** — thesis ka sabse credible section wahi banega. |
| M5 | Month | RFC 9470 + CAEP standards layer. `cadence-flowtap` real CICFlowMeter ke saath. Console. Latency/overhead benchmarks. |
| M6 | Month | Write-up, demo video, repo polish, ablation table. |

*M1 late hoga hi.* Usko bachane ke liye sabse pehle M5 ka flowtap kaato — network branch sabse kam
novel hai aur thesis uske bina bhi chalega.

---

## Ye claims mat karna

- ❌ "136 million keystrokes pe trained" → "Aalto corpus ka 10,000-participant subset (~7.3M keystrokes)"
- ❌ "State-of-the-art keystroke authentication" — CMU pe tum 2009 ke baseline se 40% peeche ho
- ❌ "p = <!--!retracted-->4.7e-21<!--/-->" — ye `iso_eers * 1.1` ka artifact hai
- ❌ "100% bot detection accuracy" — by construction separable, plus dwell bug
- ❌ "SHAP-explained predictions" — jab tak SHAP sach mein inference path mein na ho
- ❌ "AI agents detect karta hai" → "unattested input provenance aur behavioral discontinuity detect karta hai; N agent frameworks pe evaluated, leave-one-out generalisation X%"
- ❌ "Novel intrusion detection" — CICIDS2017 pe XGBoost + SMOTE ML security ka hello-world hai
- ❌ "Production-ready" / "zero-trust compliant" → "research prototype, deployed and evaluated"
- ❌ Unspoofable hone ka koi bhi claim. SDK attacker ke DOM mein chalta hai. **Ye khud bolna tumhari
  credibility badhata hai.**

---

## Repo structure

```
cadence/
├── README.md                    ← demo GIF sabse upar; pehle paragraph mein threat model
├── pyproject.toml               ← EK lockfile. sklearn pin karo warna .joblib load nahi honge.
├── cadence/
│   ├── features/keystroke.py    ← shared extractor (train == serve)
│   ├── detectors/{provenance,automation,identity,malice}.py
│   ├── fusion/sequential.py
│   ├── policy/{rfc9470.py,caep.py}
│   └── api/
├── edge/                        ← mitmproxy addon + cadence-sdk.js
├── console/
├── training/                    ← headless CLIs, critical path mein notebooks nahi
├── evaluation/
│   ├── harness/                 ← agent drivers, session replay
│   └── metrics.py               ← EER, DR@budget, time-to-detect, bootstrap CIs
├── datasets/README.md           ← download scripts + checksums, data NAHI
├── models/                      ← sirf chhote artifacts; >50 MB Releases/DVC se
├── deploy/                      ← SAM template, secrets SSM se
├── docs/{THREAT_MODEL,EVALUATION,LIMITATIONS,ETHICS}.md
└── tests/
```

**README mein isi order mein hona chahiye:** (1) 90-second demo GIF sabse upar; (2) ek paragraph
jismein threat model exactly likha ho; (3) results table **har row mein confidence intervals aur
sample counts ke saath**; (4) **ek baseline row jisse tum haar rahe ho** — scaled Manhattan <!--@cmu_baseline_scaled_manhattan_eer-->0.0962<!--/-->
tumhare <!--@cmu_lof_eer-->0.1367<!--/--> ke bagal mein; (5) **Limitations section Installation ke UPAR** (jagah hi signal hai);
(6) leave-one-agent-out number headline mein, in-distribution accuracy nahi; (7) exact reproduction
commands, pinned deps, seeds; (8) ethics/consent statement; (9) prior-art table with
"CADENCE kya alag karta hai" column; (10) ye kya **nahi** hai.

`.gitignore` mein hona chahiye: `__pycache__/`, `.pytest_cache/`, `lambda_package/`, `packages/`,
`deploy-full.zip`, `checkpoints/`, aur raw participant CSV.

---

## Git repo banane se pehle ye clear karo

1. **JWT secret aur admin password rotate karo.** `keystroke/backend/app/auth.py` aur `template.yaml`
   mein `JwtSecretKey` ka default `"change-me-in-production-use-a-long-random-string"` hai — aur ye
   CloudFormation *parameter default* hai, matlab bina override ke `sam deploy` karne pe wahi
   production signing key ban jaata hai. Koi bhi tumhare live API ke liye admin JWT bana sakta hai.
   Plaintext password `docs/PROJECT_DOCUMENTATION.md` (lines ~19-20, 498, 719) aur `auth.py` ke ek
   comment mein pada hai.
2. **`FINALLL/security_logs.json` delete karo** — 2.2 MB tumaari asli browsing history hai, jismein
   Google autocomplete keystroke-by-keystroke capture hua hai.
3. **`keystroke_export_20260513.csv` pseudonymise karo** — 49 participants ke asli poore naam hain,
   bina encryption ke, OneDrive-synced folder mein, bina backup ke. Mapping repo se bahar rakho, aur
   consent/ethics note likh lo — thesis mein waise bhi chahiye hoga.
