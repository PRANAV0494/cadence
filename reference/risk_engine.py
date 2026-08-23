"""
Advanced Risk Engine

Handles contextual risk scoring, velocity tracking, and risk decay.
Replaces simple risk_calculator.
"""

import time
import math
from typing import List, Dict, Any, Optional

class RiskEngine:
    """
    Advanced Risk Assessment Engine.
    
    Features:
    - Base risk calculation from threat events
    - Velocity tracking (detects rapid-fire attacks)
    - Time-based decay (risk score decreases over time if no new threats)
    - Contextual multipliers (e.g. key assets, time of day)
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.risk_score = 0.0
        self.last_update_time = time.time()
        self.threat_history: List[Dict[str, Any]] = []
        
        # Risk Parameters
        self.decay_rate = config.get("risk_decay_rate", 0.5) # Points per second decay
        self.velocity_window = config.get("risk_velocity_window", 60) # Seconds to look back for velocity
        self.velocity_threshold = config.get("risk_velocity_threshold", 5) # Number of threats in window to trigger multiplier
        self.max_score = 100.0

    def update(self, new_threats: List[Dict[str, Any]], keystroke_anomaly: bool, keystroke_score: float) -> Dict[str, Any]:
        """
        Update risk score based on new events and time decay.
        
        Returns:
            Dict containing current risk state.
        """
        current_time = time.time()
        time_delta = current_time - self.last_update_time
        
        # 1. Apply Strong Decay (risk decreases rapidly when no threats)
        # Decay 30% of the score per second
        decay_factor = math.exp(-0.3 * time_delta)
        self.risk_score = self.risk_score * decay_factor
        
        self.last_update_time = current_time

        # 2. Calculate Risk from CURRENT BATCH ONLY
        batch_risk = 0.0
        for threat in new_threats:
            # Add to history with timestamp
            self.threat_history.append({
                "timestamp": current_time,
                "threat": threat
            })
            
            # Simple severity mapping
            confidence = threat.get("confidence", 0.5)
            
            # Label-based severity
            label = str(threat.get("label", "")).lower()
            if label in ("normal", "background", "benign", "0"):
                impact = 0.0  # No risk for benign traffic
            elif "botnet" in label or "attack" in label or "exploit" in label:
                impact = 15.0
            elif "dos" in label or "ddos" in label:
                impact = 12.0
            else:
                impact = 5.0  # Unknown but flagged
            
            batch_risk += (impact * confidence)

        # 3. Add Keystroke Risk
        if keystroke_anomaly:
            batch_risk += 25.0 * keystroke_score

        # 4. Velocity Multiplier
        recent_count = sum(1 for t in self.threat_history if t["timestamp"] > current_time - self.velocity_window)
        velocity_mult = 1.0
        if recent_count > self.velocity_threshold:
            velocity_mult = 1.2  # Reduced multiplier

        # 5. Update Total Score
        self.risk_score += (batch_risk * velocity_mult)
        self.risk_score = min(self.max_score, self.risk_score)
        
        # 6. Prune History
        # Keep only necessary history for velocity + reporting (limit to 1000 or time window)
        self.threat_history = [t for t in self.threat_history if t["timestamp"] > current_time - 3600] # Keep 1 hour

        # 7. Determine Risk Level
        level = "low"
        if self.risk_score >= self.config.get("risk_high_threshold", 80):
            level = "critical"
        elif self.risk_score >= self.config.get("risk_medium_threshold", 50):
            level = "high"
        elif self.risk_score >= self.config.get("risk_low_threshold", 20):
            level = "medium"

        return {
            "risk_score": round(self.risk_score, 1),
            "risk_level": level,
            "velocity_checked": True,
            "recent_count": recent_count
        }

    def get_context(self) -> Dict[str, Any]:
        """Get current risk context."""
        return {
            "score": self.risk_score,
            "history_len": len(self.threat_history)
        }
