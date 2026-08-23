"""
Model Manager - Load and run inference for all 7 threat/auth models.
"""

import sys
import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Add project root to path for src imports
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Keystroke uses separate module
try:
    from src.keystroke.authenticator import KeystrokeAuthenticator
    from src.keystroke.feature_extractor import get_feature_vector
except ImportError:
    KeystrokeAuthenticator = None
    get_feature_vector = None


class ModelManager:
    """Load and run inference for BETH, BOT-IOT, CICIDS2017, CTU-13, IOT-23, UNSW-NB15, Keystroke."""

    def __init__(self, models_dir: Union[str, Path] = "models", enabled: Optional[List[str]] = None):
        self.models_dir = Path(models_dir)
        self.enabled = enabled or [
            "beth", "botiot", "cicids2017", "ctu13", "iot23", "unsw_nb15", "keystroke"
        ]
        self.models: Dict[str, Dict[str, Any]] = {}
        self._keystroke_auth: Optional[Any] = None

    def load_all(self) -> List[str]:
        """Load all enabled models. Returns list of loaded model names."""
        loaded = []
        for name in self.enabled:
            try:
                self._load_one(name)
                loaded.append(name)
            except Exception as e:
                print(f"[ModelManager] Warning: Could not load {name}: {e}")
        return loaded

    def _load_one(self, name: str):
        if name == "keystroke":
            if KeystrokeAuthenticator is None:
                raise ImportError("authenticator not found")
            self._keystroke_auth = KeystrokeAuthenticator(models_dir=self.models_dir)
            self.models["keystroke"] = {"type": "keystroke", "authenticator": self._keystroke_auth}
            return

        mdl = self.models_dir
        if name == "beth":
            features = joblib.load(mdl / "beth_features.pkl")
            scaler = joblib.load(mdl / "beth_scaler.pkl")
            model = joblib.load(mdl / "beth_xgboost_model.pkl")
            self.models[name] = {
                "type": "xgboost_sklearn",
                "model": model,
                "scaler": scaler,
                "features": features,
                "label_encoder": None,
            }
        elif name == "botiot":
            features = joblib.load(mdl / "botiot_features.pkl")
            scaler = joblib.load(mdl / "botiot_deployment_scaler.pkl")
            model = joblib.load(mdl / "botiot_randomforest_deployment_model.pkl")
            le = joblib.load(mdl / "botiot_label_encoder.pkl")
            self.models[name] = {
                "type": "sklearn",
                "model": model,
                "scaler": scaler,
                "features": features,
                "label_encoder": le,
            }
        elif name == "cicids2017":
            features = joblib.load(mdl / "cicids2017_features.pkl")
            scaler = joblib.load(mdl / "cicids2017_scaler.pkl")
            model = joblib.load(mdl / "cicids2017_xgboost_model.pkl")
            le = joblib.load(mdl / "cicids2017_label_encoder.pkl")
            self.models[name] = {
                "type": "xgboost_sklearn",
                "model": model,
                "scaler": scaler,
                "features": features,
                "label_encoder": le,
            }
        elif name == "ctu13":
            features = joblib.load(mdl / "ctu13_features.pkl")
            scaler = joblib.load(mdl / "ctu13_scaler.pkl")
            model = joblib.load(mdl / "ctu13_xgboost_model.pkl")
            self.models[name] = {
                "type": "xgboost_sklearn",
                "model": model,
                "scaler": scaler,
                "features": features,
                "label_encoder": None,
                "classes": ["Background", "Botnet"],
            }
        elif name == "iot23":
            features = joblib.load(mdl / "iot23_features.pkl")
            scaler = joblib.load(mdl / "iot23_scaler.pkl")
            model = joblib.load(mdl / "iot23_xgboost_model.pkl")
            le = joblib.load(mdl / "iot23_label_encoder.pkl")
            self.models[name] = {
                "type": "xgboost_sklearn",
                "model": model,
                "scaler": scaler,
                "features": features,
                "label_encoder": le,
            }
        elif name == "unsw_nb15":
            features = joblib.load(mdl / "unsw_nb15_features.pkl")
            scaler = joblib.load(mdl / "unsw_nb15_scaler.pkl")
            model = joblib.load(mdl / "unsw_nb15_xgboost_model.pkl")
            le = joblib.load(mdl / "unsw_nb15_label_encoder.pkl")
            self.models[name] = {
                "type": "xgboost_sklearn",
                "model": model,
                "scaler": scaler,
                "features": features,
                "label_encoder": le,
            }
        else:
            raise ValueError(f"Unknown model: {name}")

    def _prepare_features(self, name: str, data: Union[pd.DataFrame, np.ndarray, Dict]) -> np.ndarray:
        """Prepare feature matrix for model."""
        info = self.models[name]
        features = info["features"]
        if isinstance(features, (list, tuple)):
            feat_list = list(features)
        else:
            feat_list = list(features) if hasattr(features, "__iter__") else []

        if isinstance(data, dict):
            X = np.array([[data.get(f, 0) for f in feat_list]], dtype=np.float64)
        elif isinstance(data, pd.DataFrame):
            for f in feat_list:
                if f not in data.columns:
                    data = data.copy()
                    data[f] = 0
            X = data[feat_list].values.astype(np.float64)
        else:
            X = np.asarray(data, dtype=np.float64)
            if X.ndim == 1:
                X = X.reshape(1, -1)

        if X.shape[1] != len(feat_list):
            raise ValueError(
                f"Feature count mismatch for {name}: got {X.shape[1]}, expected {len(feat_list)}"
            )
        return X

    def predict_threat(
        self, model_name: str, data: Union[pd.DataFrame, np.ndarray, Dict]
    ) -> Dict[str, Any]:
        """Run threat model inference. Returns {label, confidence, model}."""
        if model_name not in self.models or model_name == "keystroke":
            return {"label": "Unknown", "confidence": 0.0, "model": model_name}

        info = self.models[model_name]
        X = self._prepare_features(model_name, data)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        X_scaled = info["scaler"].transform(X)

        model = info["model"]
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X_scaled)[0]
            pred_idx = int(np.argmax(proba))
            confidence = float(proba[pred_idx])
        else:
            pred = model.predict(X_scaled)
            pred_idx = int(pred[0]) if hasattr(pred, "__getitem__") else int(pred)
            confidence = 1.0

        le = info.get("label_encoder")
        classes = info.get("classes")
        if le is not None:
            label = str(le.inverse_transform([pred_idx])[0])
        elif classes is not None and 0 <= pred_idx < len(classes):
            label = str(classes[pred_idx])
        else:
            label = str(pred_idx)

        return {"label": label, "confidence": confidence, "model": model_name}

    def predict_keystroke(
        self, features: Union[np.ndarray, pd.DataFrame]
    ) -> Dict[str, Any]:
        """Run keystroke authentication. Returns {user_id, is_anomaly, anomaly_score}."""
        if "keystroke" not in self.models or self._keystroke_auth is None:
            return {"user_id": None, "is_anomaly": False, "anomaly_score": 0.0}

        auth = self._keystroke_auth
        user_id = auth.identify_user(features)
        score, is_anom = auth.is_anomaly(user_id, features)
        if hasattr(user_id, "item"):
            user_id = user_id.item()

        return {
            "user_id": user_id,
            "is_anomaly": bool(is_anom),
            "anomaly_score": float(score),
        }

    def explain_prediction(
        self, model_name: str, data: Union[pd.DataFrame, np.ndarray, Dict], top_n: int = 3
    ) -> Dict[str, Any]:
        """
        Explain WHY a prediction was made using feature importance.
        Returns top N contributing features.
        """
        if model_name not in self.models or model_name == "keystroke":
            return {"explanation": "N/A", "features": []}

        info = self.models[model_name]
        model = info["model"]
        features = info["features"]
        
        if isinstance(features, (list, tuple)):
            feat_list = list(features)
        else:
            feat_list = list(features) if hasattr(features, "__iter__") else []

        # Get feature importances from model
        importances = None
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "get_booster"):
            try:
                booster = model.get_booster()
                score = booster.get_score(importance_type='weight')
                importances = np.array([score.get(f'f{i}', 0) for i in range(len(feat_list))])
            except Exception:
                pass

        if importances is None or len(importances) == 0:
            return {"explanation": "No feature importance available", "features": []}

        # Prepare input data to get actual values
        X = self._prepare_features(model_name, data)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Calculate contribution (importance * normalized value)
        # Using actual feature values for context
        values = X[0] if X.ndim > 1 else X
        
        # Create feature info with importance and value
        feature_contributions = []
        for i, (feat_name, importance) in enumerate(zip(feat_list, importances)):
            if i < len(values):
                value = values[i]
            else:
                value = 0
            feature_contributions.append({
                "name": feat_name,
                "importance": float(importance),
                "value": float(value)
            })

        # Sort by importance and take top N
        feature_contributions.sort(key=lambda x: x["importance"], reverse=True)
        top_features = feature_contributions[:top_n]

        # Build explanation string
        total_importance = sum(f["importance"] for f in top_features)
        if total_importance > 0:
            explanation_parts = []
            for f in top_features:
                pct = (f["importance"] / sum(fc["importance"] for fc in feature_contributions)) * 100
                explanation_parts.append(f"{f['name']}({pct:.0f}%)")
            explanation = ", ".join(explanation_parts)
        else:
            explanation = "Unknown factors"

        return {
            "explanation": explanation,
            "features": top_features
        }
