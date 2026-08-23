"""
Pydantic models for request/response validation.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class KeystrokeEvent(BaseModel):
    """A single keystroke event captured from the frontend."""
    key: str
    event_type: str = Field(..., description="keydown or keyup")
    timestamp: float = Field(..., description="performance.now() value in ms")
    key_index: int = Field(..., description="Position index in the target string")
    key_class: str = Field(..., description="letter, number, special, or shift")
    is_backspace: bool = False
    is_paste: bool = False


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

