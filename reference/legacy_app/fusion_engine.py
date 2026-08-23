class AdaptiveFusionEngine:
    """
    Adaptive weighted fusion with escalation intelligence.
    """

    def __init__(self):
        self.base_behavioral_weight = 0.4
        self.base_network_weight = 0.6
        self.base_threshold = 0.7

    def fuse(self, behavioral_risk, network_risk, session_summary):

        behavioral_weight = self.base_behavioral_weight
        network_weight = self.base_network_weight
        threshold = self.base_threshold

        anomalies = session_summary["consecutive_anomalies"]
        beh_anomalies = session_summary.get("consecutive_behavioral_anomalies", 0)
        net_anomalies = session_summary.get("consecutive_network_anomalies", 0)

        # -------------------------------------------------
        # 1. Adaptive Weighting (fused anomaly history)
        # -------------------------------------------------
        if anomalies >= 2:
            behavioral_weight = 0.6
            network_weight = 0.4

        if anomalies >= 4:
            behavioral_weight = 0.75
            network_weight = 0.25
            threshold = 0.6

        if anomalies >= 6:
            threshold = 0.5

        # -------------------------------------------------
        # 2. Base Fusion Score
        # -------------------------------------------------
        final_risk = (
            behavioral_weight * behavioral_risk +
            network_weight * network_risk
        )

        # -------------------------------------------------
        # 3. Independent Vector Escalation
        # -------------------------------------------------
        # If behavioral anomalies persist (3+), boost fused risk
        if beh_anomalies >= 3:
            beh_boost = min(0.3, beh_anomalies * 0.05)
            final_risk = min(1.0, final_risk + beh_boost)

        # If network anomalies persist (3+), boost fused risk
        if net_anomalies >= 3:
            net_boost = min(0.3, net_anomalies * 0.05)
            final_risk = min(1.0, final_risk + net_boost)

        # -------------------------------------------------
        # 4. Decision Logic
        # -------------------------------------------------
        if final_risk >= threshold:
            decision = "BLOCK"
            risk_level = "HIGH"
        elif final_risk >= 0.5:
            decision = "MFA"
            risk_level = "MODERATE"
        else:
            decision = "ALLOW"
            risk_level = "LOW"

        # -------------------------------------------------
        # 5. Independent Vector Override
        # -------------------------------------------------
        # Persistent single-vector anomaly forces minimum action
        if beh_anomalies >= 5 or net_anomalies >= 5:
            if decision == "ALLOW":
                decision = "BLOCK"
                risk_level = "HIGH"
        elif beh_anomalies >= 3 or net_anomalies >= 3:
            if decision == "ALLOW":
                decision = "MFA"
                risk_level = "MODERATE"

        return {
            "final_risk": round(final_risk, 4),
            "risk_level": risk_level,
            "decision": decision,
            "behavioral_weight": behavioral_weight,
            "network_weight": network_weight,
            "threshold": threshold,
            "consecutive_anomalies": anomalies,
            "consecutive_behavioral_anomalies": beh_anomalies,
            "consecutive_network_anomalies": net_anomalies
        }
