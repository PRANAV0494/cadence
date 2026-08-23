"""
Multi-profile synthetic keystroke *aggregate* features for human-vs-bot experiments.

Used by:
  - augment_export_with_synthetic_bots.py (CSV augmentation)
  - human_vs_bot_keystroke_classifier.ipynb (fallback if no bot rows in CSV)

Not a physical simulator — profiles encode contrasting timing stereotypes vs typical human variability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "core_features.total_typing_duration_ms",
    "core_features.typing_speed_wpm",
    "digraph_features.digraph_consistency_score",
    "digraph_features.mean_digraph_latency",
    "digraph_features.std_digraph_latency",
    "distribution_features.iqr",
    "distribution_features.kurtosis",
    "distribution_features.max_dwell_time",
    "distribution_features.median_dwell_time",
    "distribution_features.min_dwell_time",
    "distribution_features.skewness",
    "error_features.backspace_count",
    "error_features.backspace_ratio",
    "error_features.correction_burst_length",
    "error_features.correction_latency_ms",
    "pause_features.average_pause_length_ms",
    "pause_features.long_pause_count",
    "pause_features.pause_count",
    "sequence_features.acceleration_trend",
    "sequence_features.autocorrelation_score",
    "sequence_features.burst_typing_score",
    "sequence_features.timing_entropy",
    "variability_features.coefficient_of_variation",
    "variability_features.mean_dwell_time",
    "variability_features.mean_flight_time",
    "variability_features.session_speed_drift_ms",
    "variability_features.std_dwell_time",
    "variability_features.std_flight_time",
]

PROFILE_NAMES = ("constant_delay", "fast_burst", "random_delay_band", "paste_heavy")


def clip_to_human_envelope(bot_df: pd.DataFrame, X_h: pd.DataFrame) -> pd.DataFrame:
    h_mean, h_std = X_h.mean(), X_h.std().replace(0, 1e-6)
    out = bot_df.copy()
    for c in FEATURE_COLUMNS:
        lo = float(h_mean[c] - 6 * h_std[c])
        hi = float(h_mean[c] + 6 * h_std[c])
        out[c] = out[c].clip(lo, hi)
    return out


def features_for_profile(profile: str, n: int, X_h: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict] = []
    for _ in range(n):
        if profile == "constant_delay":
            total_ms = rng.uniform(800, 2200)
            wpm = rng.uniform(35, 75)
            mean_digraph = rng.uniform(70, 140)
            std_digraph = rng.uniform(2, 12)
            digraph_consistency = rng.uniform(0.92, 0.995)
            iqr = rng.uniform(15, 80)
            kurt = rng.uniform(-1.0, 1.5)
            max_dw = rng.uniform(120, 280)
            med_dw = rng.uniform(70, 130)
            min_dw = rng.uniform(45, 95)
            skew = rng.uniform(-0.3, 0.3)
            bs_count, bs_ratio = 0, 0.0
            corr_burst, corr_lat = 0.0, 0.0
            avg_pause = rng.uniform(0.0, 25.0)
            long_pause, pause_count = 0, int(rng.poisson(0.2))
            accel = rng.uniform(-1.5, 1.5)
            autocorr = rng.uniform(0.25, 0.65)
            burst = rng.uniform(0.2, 0.45)
            entropy = rng.uniform(0.85, 1.35)
            cv = rng.uniform(0.08, 0.22)
            mean_dw = rng.uniform(75, 105)
            mean_fl = rng.uniform(75, 125)
            drift = rng.normal(0, 12)
            std_dw = rng.uniform(8, 28)
            std_fl = rng.uniform(8, 28)

        elif profile == "fast_burst":
            total_ms = rng.uniform(120, 450)
            wpm = rng.uniform(140, 320)
            mean_digraph = rng.uniform(18, 55)
            std_digraph = rng.uniform(4, 22)
            digraph_consistency = rng.uniform(0.55, 0.82)
            iqr = rng.uniform(8, 70)
            kurt = rng.uniform(-0.5, 2.2)
            max_dw = rng.uniform(90, 220)
            med_dw = rng.uniform(40, 85)
            min_dw = rng.uniform(8, 55)
            skew = rng.uniform(-0.5, 1.2)
            bs_count, bs_ratio = 0, 0.0
            corr_burst, corr_lat = 0.0, 0.0
            avg_pause = 0.0
            long_pause, pause_count = 0, 0
            accel = rng.uniform(2.0, 8.0)
            autocorr = rng.uniform(-0.2, 0.25)
            burst = rng.uniform(0.82, 0.99)
            entropy = rng.uniform(0.35, 0.85)
            cv = rng.uniform(0.18, 0.42)
            mean_dw = rng.uniform(38, 75)
            mean_fl = rng.uniform(18, 55)
            drift = rng.normal(0, 25)
            std_dw = rng.uniform(12, 55)
            std_fl = rng.uniform(12, 55)

        elif profile == "random_delay_band":
            lo_ms = rng.uniform(40, 90)
            hi_ms = rng.uniform(120, 220)
            mean_digraph = (lo_ms + hi_ms) / 2
            std_digraph = (hi_ms - lo_ms) / (2 * np.sqrt(3))
            total_ms = rng.uniform(900, 2800)
            wpm = rng.uniform(28, 68)
            digraph_consistency = rng.uniform(0.45, 0.72)
            iqr = rng.uniform(40, 140)
            kurt = rng.uniform(-1.2, 1.8)
            max_dw = rng.uniform(150, 320)
            med_dw = rng.uniform(65, 125)
            min_dw = rng.uniform(25, 75)
            skew = rng.uniform(-0.8, 0.8)
            bs_count = int(rng.choice([0, 0, 1]))
            bs_ratio = rng.uniform(0.0, 0.08) if bs_count else 0.0
            corr_burst = float(rng.choice([0, 0, 1]))
            corr_lat = rng.uniform(0, 200) if corr_burst else 0.0
            avg_pause = rng.uniform(0.0, 80.0)
            long_pause = int(rng.choice([0, 0, 1]))
            pause_count = int(rng.poisson(0.8))
            accel = rng.uniform(-3.0, 3.0)
            autocorr = rng.uniform(-0.15, 0.2)
            burst = rng.uniform(0.35, 0.65)
            entropy = rng.uniform(1.05, 1.65)
            cv = rng.uniform(0.22, 0.48)
            mean_dw = rng.uniform(60, 110)
            mean_fl = rng.uniform(55, 130)
            drift = rng.normal(0, 40)
            std_dw = rng.uniform(25, 75)
            std_fl = rng.uniform(25, 80)

        elif profile == "paste_heavy":
            total_ms = rng.uniform(40, 180)
            wpm = rng.uniform(220, 480)
            mean_digraph = rng.uniform(5, 35)
            std_digraph = rng.uniform(1, 12)
            digraph_consistency = rng.uniform(0.75, 0.95)
            iqr = rng.uniform(3, 40)
            kurt = rng.uniform(1.0, 4.5)
            max_dw = rng.uniform(40, 120)
            med_dw = rng.uniform(25, 60)
            min_dw = rng.uniform(5, 35)
            skew = rng.uniform(0.5, 2.5)
            bs_count, bs_ratio = 0, 0.0
            corr_burst, corr_lat = 0.0, 0.0
            avg_pause = rng.uniform(0.0, 15.0)
            long_pause, pause_count = 0, 0
            accel = rng.uniform(-2.0, 2.0)
            autocorr = rng.uniform(-0.35, 0.1)
            burst = rng.uniform(0.9, 1.0)
            entropy = rng.uniform(0.08, 0.45)
            cv = rng.uniform(0.04, 0.22)
            mean_dw = rng.uniform(25, 55)
            mean_fl = rng.uniform(8, 40)
            drift = rng.normal(0, 15)
            std_dw = rng.uniform(5, 35)
            std_fl = rng.uniform(5, 35)

        else:
            raise ValueError(f"Unknown profile: {profile}")

        rows.append(
            {
                "core_features.total_typing_duration_ms": total_ms,
                "core_features.typing_speed_wpm": wpm,
                "digraph_features.digraph_consistency_score": digraph_consistency,
                "digraph_features.mean_digraph_latency": mean_digraph,
                "digraph_features.std_digraph_latency": std_digraph,
                "distribution_features.iqr": iqr,
                "distribution_features.kurtosis": kurt,
                "distribution_features.max_dwell_time": max_dw,
                "distribution_features.median_dwell_time": med_dw,
                "distribution_features.min_dwell_time": min_dw,
                "distribution_features.skewness": skew,
                "error_features.backspace_count": bs_count,
                "error_features.backspace_ratio": bs_ratio,
                "error_features.correction_burst_length": corr_burst,
                "error_features.correction_latency_ms": corr_lat,
                "pause_features.average_pause_length_ms": avg_pause,
                "pause_features.long_pause_count": long_pause,
                "pause_features.pause_count": pause_count,
                "sequence_features.acceleration_trend": accel,
                "sequence_features.autocorrelation_score": autocorr,
                "sequence_features.burst_typing_score": burst,
                "sequence_features.timing_entropy": entropy,
                "variability_features.coefficient_of_variation": cv,
                "variability_features.mean_dwell_time": mean_dw,
                "variability_features.mean_flight_time": mean_fl,
                "variability_features.session_speed_drift_ms": drift,
                "variability_features.std_dwell_time": std_dw,
                "variability_features.std_flight_time": std_fl,
            }
        )

    bot_df = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    return clip_to_human_envelope(bot_df, X_h)


def generate_all_profiles(
    X_human: pd.DataFrame,
    rows_per_profile: int,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return feature matrix for synthetic bots and a Series of profile names."""
    chunks = []
    names: list[str] = []
    for prof in PROFILE_NAMES:
        part = features_for_profile(prof, rows_per_profile, X_human, rng)
        chunks.append(part)
        names.extend([prof] * len(part))
    return pd.concat(chunks, ignore_index=True), pd.Series(names, name="bot_profile")
