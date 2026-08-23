import time
from collections import defaultdict


class SessionManager:
    """
    Self-aware session intelligence engine.
    Tracks risk trends, anomaly escalation, and decay logic.
    """

    def __init__(self):
        self.sessions = defaultdict(dict)

    def _calculate_trend(self, values):
        if len(values) < 2:
            return "stable"

        if values[-1] > values[-2]:
            return "increasing"
        elif values[-1] < values[-2]:
            return "decreasing"
        return "stable"

    def update_session(self, user_id, behavioral_risk, network_risk, final_risk):

        now = time.time()

        if user_id not in self.sessions:
            self.sessions[user_id] = {
                "behavioral_history": [],
                "network_history": [],
                "final_history": [],
                "start_time": now,
                "last_event_time": now,
                "consecutive_anomalies": 0,
                "consecutive_behavioral_anomalies": 0,
                "consecutive_network_anomalies": 0,
                "locked": False
            }

        session = self.sessions[user_id]

        # Risk decay (self-healing if no anomalies for 30s)
        time_gap = now - session["last_event_time"]
        if time_gap > 30:
            session["consecutive_anomalies"] = max(
                0, session["consecutive_anomalies"] - 1
            )
            session["consecutive_behavioral_anomalies"] = max(
                0, session["consecutive_behavioral_anomalies"] - 1
            )
            session["consecutive_network_anomalies"] = max(
                0, session["consecutive_network_anomalies"] - 1
            )

        session["last_event_time"] = now

        # Append histories
        session["behavioral_history"].append(behavioral_risk)
        session["network_history"].append(network_risk)
        session["final_history"].append(final_risk)

        session["behavioral_history"] = session["behavioral_history"][-10:]
        session["network_history"] = session["network_history"][-10:]
        session["final_history"] = session["final_history"][-10:]

        behavioral_avg = sum(session["behavioral_history"]) / len(session["behavioral_history"])
        network_avg = sum(session["network_history"]) / len(session["network_history"])

        behavioral_trend = self._calculate_trend(session["behavioral_history"])
        network_trend = self._calculate_trend(session["network_history"])

        # -------------------------------------------------
        # Independent Anomaly Tracking
        # -------------------------------------------------
        # Behavioral vector (keystroke anomalies)
        if behavioral_risk > 0.8:
            session["consecutive_behavioral_anomalies"] += 1
        else:
            session["consecutive_behavioral_anomalies"] = 0

        # Network vector (traffic anomalies)
        if network_risk > 0.6:
            session["consecutive_network_anomalies"] += 1
        else:
            session["consecutive_network_anomalies"] = 0

        # Fused escalation (original logic)
        if final_risk > 0.6:
            session["consecutive_anomalies"] += 1
        else:
            session["consecutive_anomalies"] = 0

        # Cross-promote: if either independent vector is persistently anomalous,
        # boost the fused counter so adaptive fusion kicks in
        if session["consecutive_behavioral_anomalies"] >= 3:
            session["consecutive_anomalies"] = max(
                session["consecutive_anomalies"],
                session["consecutive_behavioral_anomalies"]
            )

        if session["consecutive_network_anomalies"] >= 3:
            session["consecutive_anomalies"] = max(
                session["consecutive_anomalies"],
                session["consecutive_network_anomalies"]
            )

        session_duration = now - session["start_time"]

        return {
            "behavioral_avg": round(behavioral_avg, 4),
            "network_avg": round(network_avg, 4),
            "behavioral_trend": behavioral_trend,
            "network_trend": network_trend,
            "consecutive_anomalies": session["consecutive_anomalies"],
            "consecutive_behavioral_anomalies": session["consecutive_behavioral_anomalies"],
            "consecutive_network_anomalies": session["consecutive_network_anomalies"],
            "session_duration_sec": round(session_duration, 2)
        }

    def lock_user(self, user_id):
        self.sessions[user_id]["locked"] = True

    def is_locked(self, user_id):
        return self.sessions.get(user_id, {}).get("locked", False)
