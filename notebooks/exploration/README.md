# Exploration notebooks — NON-AUTHORITATIVE

These are kept for history and for the analysis code inside them. **Results here are not project
claims.** Authoritative results live in `evaluation/` once that harness exists.

Two known-bad results in this folder, documented so nobody quotes them:

### 1. `Advanced_Keystroke_Dynamics_Authentication.ipynb` — the p-value is meaningless

Cell 20 computes:

```python
iso_eers = results_df['EER'].values
svm_eers = iso_eers * 1.1          # placeholder for comparison
t_stat, p_val = ttest_rel(iso_eers, svm_eers)   # <!--!retracted-->→ 4.689e-21<!--/-->
```

This t-tests a vector against **itself scaled by 1.1**. The resulting <!--!retracted-->`p = 4.7e-21`<!--/--> is an artifact of
arithmetic, not evidence of anything.

**Use instead:** `Final_Keystroke_Dynamics_Full.ipynb` cell 13 — a genuine paired t-test of Isolation
Forest vs One-Class SVM across 51 subjects: **t = <!--@cmu_if_vs_ocsvm_t_statistic-->3.1127<!--/-->, p = <!--@cmu_if_vs_ocsvm_p_value-->0.0031<!--/-->**.

Also avoid the "vs 0.51 global model" comparison that appears here — EER 0.5065 is chance level, so
beating it is not a finding.

### 2. `human_vs_bot_keystroke_classifier.ipynb` — 1.0 accuracy is a bug, not a result

The classifier reports perfect accuracy and AUC. It is separating classes on a **sign error**, not on
behaviour. Measured directly from the source export:

| Group | n | median `mean_dwell_time` | % negative |
|---|---|---|---|
| human | 293 | **−285.5 ms** | **85.0%** |
| bot_synthetic | 300 | +67.9 ms | 0.0% |

Dwell time cannot be negative. The cause is in the capture SDK (`edge/reference/capture.js.BUGGY`):
events are keyed by `typingInput.selectionStart`, which sits *before* the inserted character on
keydown and *after* it on keyup — so every keydown was matched with the **previous** character's
keyup. The two classes are perfectly separable by `dwell < 0`.

Consequences: 11 of the 28 model input columns are corrupt — all six distribution features,
mean/std dwell, coefficient of variation, rolling window variance, and per-key flight times.

**Salvageable** from the same data: anything derived from keydown timestamps alone — inter-key
latencies, typing speed (median 31.4 WPM, plausible), digraph, pause, and error features.
Dwell requires re-collection after the SDK is fixed.

The notebook's own honesty is worth preserving, though: `training_report.json` already states that
real-world bot detection is *not* validated without labelled real-bot sessions. That caveat was
correct — it just didn't go far enough.
