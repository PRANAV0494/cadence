class ActionEngine:

    def enforce(self, user_id, fusion_result, session_summary):

        decision = fusion_result["decision"]

        if decision == "BLOCK":
            return {
                "status": "LOCKED",
                "action": "ACCOUNT_LOCKED",
                "reason": "High risk threshold exceeded"
            }

        if decision == "MFA":
            return {
                "status": "STEP_UP_AUTH",
                "action": "REQUIRE_MFA",
                "reason": "Moderate risk detected"
            }

        return {
            "status": "TRUSTED",
            "action": "ALLOW_ACCESS",
            "reason": "Risk within acceptable limits"
        }
