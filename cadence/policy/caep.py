"""CAEP-shaped security events for local policy.

OpenID CAEP (Continuous Access Evaluation Profile) is how a relying
party tells an IdP a session is no longer good. This module emits the
JSON event; it does not POST to an IdP. Tests pin the shape so a later
transmitter cannot silently change the event type.
"""

from __future__ import annotations

import hashlib
import time

# Event types from the CAEP specification (OpenID shared signals).
SESSION_REVOKED = (
    "https://schemas.openid.net/secevent/caep/event-type/session-revoked"
)
TOKEN_CLAIMS_CHANGE = (
    "https://schemas.openid.net/secevent/caep/event-type/token-claims-change"
)


def subject_id(session_id: str) -> str:
    """The CAEP subject for a session key.

    A cookie sid is minted opaque hex and passes through. The connection
    fallback key is `host|(ip, port)` — a client address, which must not
    leave the process as a claimed-opaque handle; it is hashed instead.
    """
    if "|" not in session_id:
        return session_id
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return "conn-" + digest[:16]


def event(
    session_id: str,
    reason: str,
    *,
    now: float | None = None,
    event_type: str = SESSION_REVOKED,
) -> dict:
    """One CAEP-like SET payload. `reason` is cadence-specific detail."""
    ts = int(now if now is not None else time.time())
    return {
        "iss": "cadence",
        "iat": ts,
        "sub_id": {"format": "opaque", "id": subject_id(session_id)},
        "events": {
            event_type: {
                "event_timestamp": ts,
                "reason": reason,
            }
        },
    }
