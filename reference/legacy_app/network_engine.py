"""
Network Threat Detection Engine.
Loads all trained ML models (CICIDS2017, BETH, CTU-13, IoT-23, UNSW-NB15, BoT-IoT).
Handles both multi-class and binary classification with label encoding.
Bypasses cuML scalers (tree-based models don't need scaling).
"""

import os
import json
import joblib
import numpy as np
from app.config import NETWORK_DIR


# ---------------------------------------------------------------
# Model Registry: maps model name → file patterns & metadata
# ---------------------------------------------------------------
MODEL_REGISTRY = {
    "cicids2017": {
        "model_file": "cicids2017_xgboost_model.pkl",
        "scaler_file": "cicids2017_scaler.pkl",
        "features_file": "cicids2017_features.pkl",
        "label_encoder_file": "cicids2017_label_encoder.pkl",
        "metadata_file": "model_metadata.json",
        "scaler_is_cuml": True,
        "classification": "multi",
    },
    "beth": {
        "model_file": "beth_xgboost_model.pkl",
        "scaler_file": "beth_scaler.pkl",
        "features_file": "beth_features.pkl",
        "metadata_file": "beth_metadata.json",
        "label_encoder_file": None,
        "scaler_is_cuml": True,
        "classification": "binary",
    },
    "ctu13": {
        "model_file": "ctu13_xgboost_model.pkl",
        "scaler_file": "ctu13_scaler.pkl",
        "features_file": "ctu13_features.pkl",
        "metadata_file": "ctu13_metadata.json",
        "label_encoder_file": None,
        "scaler_is_cuml": False,
        "classification": "binary",
    },
    "iot23": {
        "model_file": "iot23_xgboost_model.pkl",
        "scaler_file": "iot23_scaler.pkl",
        "features_file": "iot23_features.pkl",
        "metadata_file": "iot23_metadata.json",
        "label_encoder_file": "iot23_label_encoder.pkl",
        "scaler_is_cuml": False,
        "classification": "multi",
    },
    "unsw_nb15": {
        "model_file": "unsw_nb15_xgboost_model.pkl",
        "scaler_file": "unsw_nb15_scaler.pkl",
        "features_file": "unsw_nb15_features.pkl",
        "metadata_file": "unsw_nb15_metadata.json",
        "label_encoder_file": "unsw_nb15_label_encoder.pkl",
        "scaler_is_cuml": True,
        "classification": "multi",
    },
    "botiot": {
        "model_file": "botiot_randomforest_deployment_model.pkl",
        "scaler_file": "botiot_deployment_scaler.pkl",
        "features_file": "botiot_features.pkl",
        "metadata_file": "botiot_deployment_metadata.json",
        "label_encoder_file": "botiot_label_encoder.pkl",
        "scaler_is_cuml": True,       # both model AND scaler are cuML
        "model_is_cuml": True,        # RandomForest is cuML
        "classification": "multi",
    },
}

# Attack types that indicate threats (for risk calculation)
BENIGN_LABELS = {
    "BENIGN", "benign", "Benign", "Normal", "Background", "(empty)"
}


class NetworkEngine:
    """
    Network threat detection engine.
    Supports multiple models, multi-class classification, and cuML bypass.
    """

    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.feature_lists = {}
        self.label_encoders = {}
        self.metadata = {}
        self._preload_all()

    def _preload_all(self):
        """Pre-load all available models at startup."""
        print("\n[NetworkEngine] Loading models...")

        for name, config in MODEL_REGISTRY.items():
            try:
                self._load_model(name, config)
                n_feat = len(self.feature_lists.get(name, []))
                print(f"  ✓ {name}: {n_feat} features, "
                      f"type={config['classification']}")
            except Exception as e:
                print(f"  ✗ {name}: FAILED - {e}")

        print(f"[NetworkEngine] {len(self.models)} models loaded.\n")

    def _load_model(self, name, config):
        """Load a single model and its associated files."""
        model_path = os.path.join(NETWORK_DIR, config["model_file"])

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")

        # Skip cuML models entirely (can't load without RAPIDS)
        if config.get("model_is_cuml", False):
            raise ImportError(
                f"Model {name} requires cuML (GPU). Skipping."
            )

        # Load XGBoost model
        self.models[name] = joblib.load(model_path)

        # Load features list (always sklearn/plain Python)
        features_path = os.path.join(NETWORK_DIR, config["features_file"])
        if os.path.exists(features_path):
            self.feature_lists[name] = joblib.load(features_path)

        # Load scaler (skip if cuML)
        scaler_path = os.path.join(NETWORK_DIR, config["scaler_file"])
        if not config.get("scaler_is_cuml", False) and os.path.exists(scaler_path):
            self.scalers[name] = joblib.load(scaler_path)
        else:
            self.scalers[name] = None  # Will skip scaling

        # Load label encoder (always sklearn)
        if config.get("label_encoder_file"):
            le_path = os.path.join(NETWORK_DIR, config["label_encoder_file"])
            if os.path.exists(le_path):
                self.label_encoders[name] = joblib.load(le_path)

        # Load metadata (JSON)
        meta_path = os.path.join(NETWORK_DIR, config["metadata_file"])
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                self.metadata[name] = json.load(f)

    def get_available_models(self):
        """Return list of successfully loaded model names."""
        return list(self.models.keys())

    def predict(self, model_name, network_features):
        """
        Run prediction on the given model.
        Returns risk score, decision, and attack type (if multi-class).
        """
        try:
            if model_name not in self.models:
                available = ", ".join(self.get_available_models())
                return {
                    "model": model_name,
                    "error": f"Model {model_name} not found. Available: {available}",
                    "network_risk": 0.0,
                    "decision": "ERROR"
                }

            model = self.models[model_name]
            scaler = self.scalers[model_name]
            features = self.feature_lists.get(model_name, [])
            expected_features = len(features)
            config = MODEL_REGISTRY[model_name]

            X = np.array(network_features, dtype=np.float64).reshape(1, -1)

            # Feature size validation
            if expected_features > 0 and X.shape[1] != expected_features:
                return {
                    "model": model_name,
                    "error": f"Expected {expected_features} features, got {X.shape[1]}",
                    "network_risk": 0.0,
                    "decision": "ERROR"
                }

            # Scale if scaler available (sklearn-only)
            X_input = scaler.transform(X) if scaler is not None else X

            # Predict
            risk = 0.0
            attack_type = None
            attack_confidence = 0.0

            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X_input)[0]
                pred_class = int(np.argmax(proba))

                if config["classification"] == "multi":
                    # Multi-class: compute risk as 1 - P(benign)
                    le = self.label_encoders.get(model_name)
                    meta = self.metadata.get(model_name, {})

                    if le is not None:
                        label = le.inverse_transform([pred_class])[0]
                    elif "class_mapping" in meta:
                        label = meta["class_mapping"].get(str(pred_class), f"class_{pred_class}")
                    else:
                        label = f"class_{pred_class}"

                    # Risk = 1 - probability of benign classes
                    benign_prob = 0.0
                    for i, p in enumerate(proba):
                        if le is not None:
                            try:
                                cls = le.inverse_transform([i])[0]
                            except:
                                cls = f"class_{i}"
                        elif "class_mapping" in meta:
                            cls = meta["class_mapping"].get(str(i), "")
                        else:
                            cls = ""
                        if cls in BENIGN_LABELS:
                            benign_prob += p

                    risk = float(1.0 - benign_prob)
                    attack_confidence = float(max(proba))

                    if label not in BENIGN_LABELS:
                        attack_type = str(label)
                    else:
                        attack_type = None

                else:
                    # Binary: prob of positive class (threat)
                    if len(proba) >= 2:
                        risk = float(proba[1])
                    else:
                        risk = float(proba[0])
                    attack_confidence = risk

            elif hasattr(model, "decision_function"):
                score = model.decision_function(X_input)[0]
                risk = float(1 / (1 + np.exp(-score)))

            else:
                pred = model.predict(X_input)[0]
                risk = 1.0 if pred != 0 else 0.0

            decision = "ANOMALY" if risk > 0.5 else "NORMAL"

            result = {
                "model": model_name,
                "network_risk": round(risk, 4),
                "decision": decision,
                "confidence": round(attack_confidence, 4),
            }

            if attack_type:
                result["attack_type"] = attack_type

            return result

        except Exception as e:
            return {
                "model": model_name,
                "error": f"Prediction error: {str(e)}",
                "network_risk": 0.0,
                "decision": "ERROR"
            }
