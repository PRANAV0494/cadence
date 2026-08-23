"""
Free-Form Keystroke Dynamics — Model Training Pipeline
======================================================
Trains per-user Isolation Forest models on the KeyRecs free-text dataset.

Features per session:
  - hold_mean, hold_std           (DU.key1.key1 = hold time approximation)
  - dd_mean, dd_std               (DD.key1.key2)
  - du_mean, du_std               (DU.key1.key2)
  - ud_mean, ud_std               (UD.key1.key2)
  - uu_mean, uu_std               (UU.key1.key2)
  - typing_speed                  (1 / dd_mean)
  - consistency_ratio             (dd_std / dd_mean)
  - dd_max, dd_min, dd_range
  Total: 15 features per session

Output:
  models/keystroke/freeform_user_models/
    user_{participant}_model.pkl
    user_{participant}_scaler.pkl
    user_{participant}_metadata.json
"""

import os
import json
import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_curve
import joblib

warnings.filterwarnings("ignore")

# ── Paths ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "datasets", "keyrecs", "free-text.csv")
OUT_DIR = os.path.join(BASE_DIR, "models", "keystroke", "freeform_user_models")
os.makedirs(OUT_DIR, exist_ok=True)

FEATURE_NAMES = [
    "hold_mean", "hold_std",
    "dd_mean", "dd_std",
    "du_mean", "du_std",
    "ud_mean", "ud_std",
    "uu_mean", "uu_std",
    "typing_speed", "consistency_ratio",
    "dd_max", "dd_min", "dd_range",
]


def load_and_clean(path):
    """Load the KeyRecs free-text CSV and clean it."""
    print(f"[1/5] Loading dataset from {path}")
    df = pd.read_csv(path, low_memory=False)

    # Drop unnamed columns
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    # Rename columns for clarity
    df.columns = ["participant", "session", "key1", "key2",
                   "hold_time", "dd_time", "du_time", "ud_time", "uu_time"]

    # Convert to numeric, drop NaNs
    for col in ["hold_time", "dd_time", "du_time", "ud_time", "uu_time"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["dd_time", "ud_time"])
    print(f"    Cleaned: {before} -> {len(df)} rows ({before - len(df)} dropped)")
    print(f"    Participants: {df['participant'].nunique()}")
    print(f"    Sessions per user: {df.groupby('participant')['session'].nunique().describe().to_dict()}")

    return df


def extract_session_features(session_df):
    """Extract a 15-feature vector from one user-session."""
    hold = session_df["hold_time"].dropna()
    dd = session_df["dd_time"].dropna()
    du = session_df["du_time"].dropna()
    ud = session_df["ud_time"].dropna()
    uu = session_df["uu_time"].dropna()

    def safe_mean(s): return s.mean() if len(s) > 0 else 0
    def safe_std(s): return s.std() if len(s) > 1 else 0

    dd_mean = safe_mean(dd)
    dd_std_val = safe_std(dd)

    features = {
        "hold_mean": safe_mean(hold),
        "hold_std": safe_std(hold),
        "dd_mean": dd_mean,
        "dd_std": dd_std_val,
        "du_mean": safe_mean(du),
        "du_std": safe_std(du),
        "ud_mean": safe_mean(ud),
        "ud_std": safe_std(ud),
        "uu_mean": safe_mean(uu),
        "uu_std": safe_std(uu),
        "typing_speed": 1.0 / dd_mean if dd_mean > 0 else 0,
        "consistency_ratio": dd_std_val / dd_mean if dd_mean > 0 else 0,
        "dd_max": dd.max() if len(dd) > 0 else 0,
        "dd_min": dd.min() if len(dd) > 0 else 0,
        "dd_range": (dd.max() - dd.min()) if len(dd) > 0 else 0,
    }
    return features


def build_feature_matrix(df):
    """Build per-user feature matrix using sliding windows of digraphs."""
    print("[2/5] Extracting features via sliding windows...")
    WINDOW_SIZE = 50    # digraphs per window
    STEP_SIZE = 25      # overlap
    records = []

    for (participant, session), group in df.groupby(["participant", "session"]):
        group = group.reset_index(drop=True)
        n = len(group)
        if n < WINDOW_SIZE:
            # Use the whole session as one sample
            feats = extract_session_features(group)
            feats["participant"] = participant
            feats["session"] = session
            records.append(feats)
            continue

        # Sliding window
        for start in range(0, n - WINDOW_SIZE + 1, STEP_SIZE):
            window = group.iloc[start:start + WINDOW_SIZE]
            feats = extract_session_features(window)
            feats["participant"] = participant
            feats["session"] = session
            records.append(feats)

    feat_df = pd.DataFrame(records)
    print(f"    Feature matrix: {feat_df.shape}")
    print(f"    Samples per user: min={feat_df.groupby('participant').size().min()}, "
          f"max={feat_df.groupby('participant').size().max()}, "
          f"median={feat_df.groupby('participant').size().median():.0f}")

    return feat_df


def compute_eer(genuine_scores, impostor_scores):
    """Compute Equal Error Rate."""
    labels = np.concatenate([np.ones(len(genuine_scores)), np.zeros(len(impostor_scores))])
    scores = np.concatenate([genuine_scores, impostor_scores])
    fpr, tpr, thresholds = roc_curve(labels, scores)
    fnr = 1 - tpr
    idx = np.nanargmin(np.abs(fpr - fnr))
    eer = (fpr[idx] + fnr[idx]) / 2
    return eer, thresholds[idx] if idx < len(thresholds) else 0


def train_models(feat_df):
    """Train per-user Isolation Forest models."""
    print("[3/5] Training per-user Isolation Forest models...")
    participants = feat_df["participant"].unique()
    results = {}
    feature_cols = FEATURE_NAMES

    trained = 0
    skipped = 0

    for participant in sorted(participants):
        user_data = feat_df[feat_df["participant"] == participant][feature_cols].values

        if len(user_data) < 3:
            skipped += 1
            continue

        # Fit scaler
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(user_data)

        # Train Isolation Forest
        model = IsolationForest(
            n_estimators=100,
            contamination=0.1,
            random_state=42,
            max_samples="auto",
        )
        model.fit(X_scaled)

        # Compute scores for genuine user
        genuine_scores = model.decision_function(X_scaled)

        # Compute EER using other users as impostors
        other_data = feat_df[feat_df["participant"] != participant][feature_cols].values
        if len(other_data) > 0:
            sample_size = min(len(other_data), 200)
            np.random.seed(42)
            impostor_sample = other_data[np.random.choice(len(other_data), sample_size, replace=False)]
            impostor_scaled = scaler.transform(impostor_sample)
            impostor_scores = model.decision_function(impostor_scaled)
            eer, eer_threshold = compute_eer(genuine_scores, impostor_scores)
        else:
            eer = 0.15
            eer_threshold = 0.0

        # Save model artifacts
        prefix = f"user_{participant}"
        joblib.dump(model, os.path.join(OUT_DIR, f"{prefix}_model.pkl"))
        joblib.dump(scaler, os.path.join(OUT_DIR, f"{prefix}_scaler.pkl"))

        metadata = {
            "participant": participant,
            "n_sessions": int(len(user_data)),
            "n_features": len(feature_cols),
            "feature_names": feature_cols,
            "eer": round(float(eer), 4),
            "eer_threshold": round(float(eer_threshold), 6),
            "model_type": "IsolationForest",
            "dataset": "KeyRecs_free-text",
        }
        with open(os.path.join(OUT_DIR, f"{prefix}_metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)

        results[participant] = {"eer": eer, "sessions": len(user_data)}
        trained += 1

    print(f"    Trained: {trained} users, Skipped: {skipped} (too few sessions)")
    return results


def print_summary(results):
    """Print training summary."""
    print("[4/5] Training Summary")
    eers = [v["eer"] for v in results.values()]
    print(f"    Users trained: {len(results)}")
    print(f"    Mean EER: {np.mean(eers):.4f}")
    print(f"    Median EER: {np.median(eers):.4f}")
    print(f"    Min EER: {np.min(eers):.4f}")
    print(f"    Max EER: {np.max(eers):.4f}")
    print(f"    Users with EER < 0.15: {sum(1 for e in eers if e < 0.15)}")
    print(f"    Users with EER < 0.10: {sum(1 for e in eers if e < 0.10)}")


def verify_models():
    """Quick verification of saved models."""
    print("[5/5] Verifying saved models...")
    model_files = [f for f in os.listdir(OUT_DIR) if f.endswith("_model.pkl")]
    print(f"    Model files: {len(model_files)}")

    # Load and test one model
    if model_files:
        sample_model_name = model_files[0]
        participant = sample_model_name.replace("user_", "").replace("_model.pkl", "")
        model = joblib.load(os.path.join(OUT_DIR, sample_model_name))
        scaler = joblib.load(os.path.join(OUT_DIR, f"user_{participant}_scaler.pkl"))
        with open(os.path.join(OUT_DIR, f"user_{participant}_metadata.json")) as f:
            meta = json.load(f)

        # Test with random features
        test_features = np.random.rand(1, len(FEATURE_NAMES))
        test_scaled = scaler.transform(test_features)
        score = model.decision_function(test_scaled)[0]
        print(f"    Test prediction for {participant}: score={score:.4f}, threshold={meta['eer_threshold']:.4f}")
        print(f"    Decision: {'NORMAL' if score >= meta['eer_threshold'] else 'ANOMALY'}")

    print("\n✅ All models saved to:", OUT_DIR)


if __name__ == "__main__":
    print("=" * 60)
    print("Free-Form Keystroke Dynamics — Model Training")
    print("=" * 60)

    df = load_and_clean(DATA_PATH)
    feat_df = build_feature_matrix(df)
    results = train_models(feat_df)
    print_summary(results)
    verify_models()
