"""
Free-Form Keystroke Engine
==========================
Loads per-user Isolation Forest models trained on the KeyRecs free-text dataset.
Accepts 15 digraph-aggregate features and returns NORMAL/ANOMALY decisions.

Feature order (must match SDK output):
  hold_mean, hold_std, dd_mean, dd_std, du_mean, du_std,
  ud_mean, ud_std, uu_mean, uu_std, typing_speed,
  consistency_ratio, dd_max, dd_min, dd_range
"""

import os
import json
import numpy as np
import joblib
from pathlib import Path


FEATURE_NAMES = [
    "hold_mean", "hold_std",
    "dd_mean", "dd_std",
    "du_mean", "du_std",
    "ud_mean", "ud_std",
    "uu_mean", "uu_std",
    "typing_speed", "consistency_ratio",
    "dd_max", "dd_min", "dd_range",
]


class FreeFormKeystrokeEngine:
    """Per-user free-form keystroke anomaly detector."""

    def __init__(self, model_dir=None):
        if model_dir is None:
            model_dir = str(
                Path(__file__).resolve().parent.parent
                / "models" / "keystroke" / "freeform_user_models"
            )
        self.model_dir = model_dir
        self.models = {}
        self._load_models()

    def _load_models(self):
        """Load all per-user models at startup."""
        if not os.path.isdir(self.model_dir):
            print(f"[FreeFormKeystrokeEngine] Model dir not found: {self.model_dir}")
            return

        loaded = 0
        for f in os.listdir(self.model_dir):
            if f.endswith("_model.pkl"):
                uid = f.replace("user_", "").replace("_model.pkl", "")
                try:
                    model = joblib.load(os.path.join(self.model_dir, f))
                    scaler = joblib.load(
                        os.path.join(self.model_dir, f"user_{uid}_scaler.pkl")
                    )
                    meta_path = os.path.join(
                        self.model_dir, f"user_{uid}_metadata.json"
                    )
                    with open(meta_path) as mf:
                        meta = json.load(mf)

                    self.models[uid] = {
                        "model": model,
                        "scaler": scaler,
                        "threshold": meta.get("eer_threshold", 0),
                        "eer": meta.get("eer", 0),
                    }
                    loaded += 1
                except Exception as e:
                    print(f"[FreeFormKeystrokeEngine] Failed to load {uid}: {e}")

        print(f"[FreeFormKeystrokeEngine] Loaded {loaded} free-form user models.")

    def get_users(self):
        """Return sorted list of available user IDs."""
        return sorted(self.models.keys())

    def predict(self, user_id, features_dict):
        """
        Predict whether the typing pattern matches the claimed user.

        Args:
            user_id: User identifier (e.g. 'p001')
            features_dict: Dict with keys matching FEATURE_NAMES, or a list of 15 floats.

        Returns:
            dict with user_id, raw_score, threshold, behavioral_risk, decision
        """
        if user_id not in self.models:
            return {
                "user_id": user_id,
                "error": f"No free-form model for user '{user_id}'",
                "decision": "ERROR",
                "behavioral_risk": 0.5,
            }

        entry = self.models[user_id]
        model = entry["model"]
        scaler = entry["scaler"]
        threshold = entry["threshold"]

        try:
            # Accept either dict or list
            if isinstance(features_dict, dict):
                feature_vector = [features_dict.get(name, 0) for name in FEATURE_NAMES]
            elif isinstance(features_dict, list):
                feature_vector = features_dict
            else:
                feature_vector = list(features_dict)

            X = np.array(feature_vector, dtype=float).reshape(1, -1)
            X_scaled = scaler.transform(X)
            score = model.decision_function(X_scaled)[0]

            # Decision based on EER threshold
            decision = "NORMAL" if score >= threshold else "ANOMALY"

            # Map score to 0-1 risk
            risk = max(0, min(1, 0.5 - score))

            return {
                "user_id": user_id,
                "raw_score": round(float(score), 6),
                "threshold": round(float(threshold), 6),
                "behavioral_risk": round(float(risk), 4),
                "decision": decision,
            }

        except Exception as e:
            return {
                "user_id": user_id,
                "error": f"Prediction error: {e}",
                "decision": "ERROR",
                "behavioral_risk": 0.5,
            }
