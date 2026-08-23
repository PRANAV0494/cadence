"""
Pydantic models for request/response validation.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional, Dict, Any


class KeystrokeEvent(BaseModel):
    """
    A single keystroke event, as emitted by edge/cadence-sdk.js.

    The previous schema keyed events by `key_index`, a caret position. That is
    not key identity — the caret sits before the inserted character on keydown
    and after it on keyup — so pairing on it matched every press with the
    previous character's release, and 85% of collected human dwell times came
    out negative. `seq` replaces it: a monotonic counter stamped on keydown and
    echoed on the matching keyup, which survives key rollover.

    A payload carrying `key_index` is from a client predating that fix; its
    dwell-derived features are unusable, so submission is rejected rather than
    silently stored.
    """

    event_type: str = Field(..., description="keydown or keyup")
    timestamp: float = Field(..., description="performance.now() value in ms")
    seq: Optional[int] = Field(
        None,
        description=(
            "Press identity: monotonic counter assigned on keydown, echoed on "
            "the matching keyup. Null on a keyup whose keydown was not captured."
        ),
    )
    code: Optional[str] = Field(
        None, description="event.code — the physical key, layout independent"
    )
    key: Optional[str] = Field(
        None, description="event.key — the character produced, null for paste"
    )
    is_backspace: bool = False
    is_modifier: bool = Field(
        False,
        description=(
            "True for any key that produces no character — not only Shift, "
            "Control and Alt but also Tab, Escape, Enter, Delete, the arrow "
            "keys and F1-F12. The name is narrower than the meaning, kept for "
            "wire compatibility; read it as 'produced no character'. These are "
            "recorded but excluded from timing statistics, because a Shift held "
            "across a capital letter dwells far longer than the letter and "
            "counting it as a character inflates typing speed."
        ),
    )
    is_paste: bool = False
    pasted_length: Optional[int] = Field(
        None, description="Character count of a paste. The content is never sent."
    )
    is_trusted: Optional[bool] = Field(
        None, description="event.isTrusted — false for synthesised input."
    )

    @field_validator("event_type")
    @classmethod
    def _known_event_type(cls, v: str) -> str:
        if v not in {"keydown", "keyup"}:
            raise ValueError(f"event_type must be 'keydown' or 'keyup', got {v!r}")
        return v

    model_config = ConfigDict(extra="forbid")


class SubmissionPayload(BaseModel):
    """Payload sent from frontend for one phrase attempt."""
    username: str = Field(..., min_length=1, max_length=50)
    session_id: str = Field(..., description="UUID generated on frontend")
    attempt_number: int = Field(..., ge=1)
    phrase_id: str = Field(..., description="Identifier for the target phrase")
    phrase_version: int = Field(1, description="Version of the phrase at time of typing")
    events: List[KeystrokeEvent]
    consent_given: bool = Field(True, description="User consented to biometric capture")
    timestamp: str = Field(..., description="ISO 8601 timestamp")


class AdminLoginRequest(BaseModel):
    """Admin login credentials."""
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class DashboardSummary(BaseModel):
    """Summary statistics for the admin dashboard."""
    total_users: int
    total_sessions: int
    total_attempts: int
    latest_submissions: List[Dict[str, Any]]


class SessionRecord(BaseModel):
    """A single session record for the admin table."""
    username: str
    session_id: str
    attempt_number: int
    phrase_id: str
    phrase_version: int = 1
    timestamp: str
    features: Dict[str, Any]
    backspace_count: int = 0
    paste_detected: bool = False


class FeatureResponse(BaseModel):
    """Detailed feature data for one attempt."""
    username: str
    session_id: str
    attempt_number: int
    phrase_id: str
    phrase_version: int = 1
    timestamp: str
    core_features: Dict[str, Any]
    variability_features: Dict[str, Any]
    distribution_features: Dict[str, Any]
    digraph_features: Dict[str, Any]
    pause_features: Dict[str, Any]
    error_features: Dict[str, Any]
    sequence_features: Dict[str, Any]


# ── Phrase Management Models ───────────────────────────────────

class PhraseCreateRequest(BaseModel):
    """Create a new typing phrase."""
    text: str = Field(..., min_length=1, max_length=200)
    category: str = Field("password-style", description="password-style, mixed-string, or sentence")
    order: int = Field(99, ge=1)
    max_attempts: int = Field(1, ge=1, le=10)


class PhraseUpdateRequest(BaseModel):
    """Update an existing phrase (all fields optional)."""
    text: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = None
    order: Optional[int] = Field(None, ge=1)
    max_attempts: Optional[int] = Field(None, ge=1, le=10)
    active: Optional[bool] = None

