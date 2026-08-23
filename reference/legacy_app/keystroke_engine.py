import os
import json
import joblib
import numpy as np
from app.config import KEYSTROKE_PER_USER_DIR


class KeystrokeEngine:
    """
    Per-user keystroke behavioral authentication engine.
    Uses IsolationForest with stored EER threshold.
    """

    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.thresholds = {}

    # ---------------------------------------------------------
    # INTERNAL: Resolve user artifact paths
    # ---------------------------------------------------------
    def _get_user_paths(self, user_id):
        model_path = os.path.join(
            KEYSTROKE_PER_USER_DIR,
            f"user_{user_id}_model.pkl"
        )

        scaler_path = os.path.join(
            KEYSTROKE_PER_USER_DIR,
            f"user_{user_id}_scaler.pkl"
        )

        metadata_path = os.path.join(
            KEYSTROKE_PER_USER_DIR,
            f"user_{user_id}_metadata.json"
        )

        return model_path, scaler_path, metadata_path

    # ---------------------------------------------------------
    # LOAD MODEL (with caching)
    # ---------------------------------------------------------
    def load_user_model(self, user_id):

        if user_id in self.models:
            return (
                self.models[user_id],
                self.scalers[user_id],
                self.thresholds[user_id]
            )

        model_path, scaler_path, metadata_path = self._get_user_paths(user_id)

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found for user: {user_id}")

        if not os.path.exists(scaler_path):
            raise FileNotFoundError(f"Scaler not found for user: {user_id}")

        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"Metadata not found for user: {user_id}")

        try:
            model = joblib.load(model_path)
            scaler = joblib.load(scaler_path)

            with open(metadata_path, "r") as f:
                metadata = json.load(f)

            threshold = metadata["eer_threshold"]

            # Cache for future calls
            self.models[user_id] = model
            self.scalers[user_id] = scaler
            self.thresholds[user_id] = threshold

            return model, scaler, threshold

        except Exception as e:
            raise RuntimeError(f"Failed to load artifacts for {user_id}: {e}")

    # ---------------------------------------------------------
    # PREDICTION
    # ---------------------------------------------------------
    def predict(self, user_id, keystroke_features):
        """
        Evaluate keystroke features against user's model.

        Returns:
        {
            user_id,
            raw_score,
            threshold,
            behavioral_risk,
            decision
        }
        """

        try:
            model, scaler, threshold = self.load_user_model(user_id)

            # Convert input to numpy array
            X = np.array(keystroke_features).reshape(1, -1)

            # Scale
            X_scaled = scaler.transform(X)

            # IsolationForest decision score
            score = model.decision_function(X_scaled)[0]

            # Decision logic
            decision = "NORMAL" if score >= threshold else "ANOMALY"

            # Risk calibration (smooth sigmoid around threshold)
            # Stronger anomaly scaling
            if score < threshold:
                # Normalize anomaly distance
                anomaly_strength = abs(score - threshold)
                risk = min(1.0, 0.6 + anomaly_strength * 3)
            else:
                risk = max(0.0, 0.4 - (score - threshold))


            return {
                "user_id": user_id,
                "raw_score": round(float(score), 6),
                "threshold": round(float(threshold), 6),
                "behavioral_risk": round(float(risk), 4),
                "decision": decision
            }

        except FileNotFoundError as e:
            return {
                "user_id": user_id,
                "error": str(e),
                "decision": "UNKNOWN"
            }

        except Exception as e:
            return {
                "user_id": user_id,
                "error": f"Prediction error: {str(e)}",
                "decision": "ERROR"
            }
