"""
FastAPI application with Mangum adapter for AWS Lambda.

Endpoints:
  POST /api/submit              – Accept raw keystroke data
  GET  /api/phrases             – Get active phrases (public)
  POST /api/admin/login         – Admin JWT login
  GET  /api/admin/dashboard     – Summary stats
  GET  /api/admin/sessions      – Filterable session list
  GET  /api/admin/session/{u}/{k} – Detailed view
  GET  /api/admin/export        – CSV download
  GET  /api/admin/phrases       – All phrases (incl. inactive)
  POST /api/admin/phrases       – Create phrase
  PUT  /api/admin/phrases/{id}  – Update phrase
  DELETE /api/admin/phrases/{id} – Delete phrase
  POST /api/admin/phrases/seed  – Seed defaults
  GET  /api/admin/audit-log     – Phrase audit log
"""

import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from cadence.api.models import (
    SubmissionPayload,
    AdminLoginRequest,
    AdminLoginResponse,
    PhraseCreateRequest,
    PhraseUpdateRequest,
)
from cadence.api.auth import authenticate_admin, create_access_token, verify_token
from cadence.features.keystroke import CorruptEventStreamError, extract_features
from cadence.api.db import (
    store_session,
    get_dashboard_stats,
    query_sessions,
    get_session_detail,
)
from cadence.api.csv_export import build_csv
from cadence.api.phrases_db import (
    create_phrase,
    update_phrase,
    delete_phrase,
    hard_delete_phrase,
    get_phrase,
    get_all_phrases,
    get_active_phrases,
    seed_default_phrases,
    get_audit_logs,
)

# ── App setup ──────────────────────────────────────────────────
app = FastAPI(
    title="Keystroke Dynamics API",
    version="2.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# CORS — allow the Firebase-hosted frontend
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5000,http://localhost:5500,http://localhost:3000,http://127.0.0.1:5000,http://127.0.0.1:5500",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# ── Simple rate limiting ───────────────────────────────────────
_rate_store: dict = {}
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "60"))


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - 60

    timestamps = _rate_store.get(client_ip, [])
    timestamps = [t for t in timestamps if t > window_start]

    if len(timestamps) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    timestamps.append(now)
    _rate_store[client_ip] = timestamps

    return await call_next(request)


# ══════════════════════════════════════════════════════════════
# PUBLIC ENDPOINTS
# ══════════════════════════════════════════════════════════════

@app.get("/api/phrases")
async def public_get_phrases():
    """Return active phrases for the frontend (public, no auth)."""
    phrases = get_active_phrases()
    return {"phrases": phrases}


@app.post("/api/submit", status_code=201)
async def submit_keystroke_data(payload: SubmissionPayload):
    """Accept raw keystroke events, extract features, store in DynamoDB."""
    if not payload.consent_given:
        raise HTTPException(status_code=400, detail="User consent is required")

    if not payload.events:
        raise HTTPException(status_code=400, detail="No keystroke events provided")

    events = [e.model_dump() for e in payload.events]

    try:
        features = extract_features(events)
    except CorruptEventStreamError as exc:
        # A client sending events we cannot pair correctly is a client error.
        # Storing the resulting features would repeat the original mistake:
        # 85% of the first collection round has negative dwell times because
        # nothing rejected them at ingest.
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unusable_event_stream",
                "message": str(exc),
                "remedy": (
                    "Update the client to edge/cadence-sdk.js, which stamps each "
                    "keydown with a 'seq' and echoes it on the matching keyup."
                ),
            },
        ) from exc

    backspace_count = sum(1 for e in events if e.get("is_backspace") and e["event_type"] == "keydown")
    paste_detected = any(e.get("is_paste") for e in events)

    store_session(
        username=payload.username,
        session_id=payload.session_id,
        attempt_number=payload.attempt_number,
        phrase_id=payload.phrase_id,
        timestamp=payload.timestamp,
        features=features,
        phrase_version=payload.phrase_version,
        backspace_count=backspace_count,
        paste_detected=paste_detected,
        raw_event_count=len(events),
    )

    return {
        "status": "success",
        "message": "Keystroke data processed and stored",
        "features_summary": {
            "typing_speed_wpm": features["core_features"]["typing_speed_wpm"],
            "total_duration_ms": features["core_features"]["total_typing_duration_ms"],
            "backspace_ratio": features["error_features"]["backspace_ratio"],
        },
    }


# ══════════════════════════════════════════════════════════════
# ADMIN AUTH
# ══════════════════════════════════════════════════════════════

@app.post("/api/admin/login", response_model=AdminLoginResponse)
async def admin_login(creds: AdminLoginRequest):
    """Authenticate admin and return JWT."""
    if not authenticate_admin(creds.username, creds.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(data={"sub": creds.username})
    return AdminLoginResponse(access_token=token)


# ══════════════════════════════════════════════════════════════
# ADMIN — DASHBOARD & SESSIONS
# ══════════════════════════════════════════════════════════════

@app.get("/api/admin/dashboard")
async def admin_dashboard(admin: str = Depends(verify_token)):
    """Return dashboard summary statistics."""
    stats = get_dashboard_stats()
    return stats


@app.get("/api/admin/sessions")
async def admin_sessions(
    admin: str = Depends(verify_token),
    username: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    phrase_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Return filterable list of session records."""
    records = query_sessions(
        username=username,
        session_id=session_id,
        phrase_id=phrase_id,
        date_from=date_from,
        date_to=date_to,
    )
    return {"sessions": records, "count": len(records)}


@app.get("/api/admin/session/{username}/{sort_key}")
async def admin_session_detail(
    username: str,
    sort_key: str,
    admin: str = Depends(verify_token),
):
    """Return detailed feature data for a single attempt."""
    record = get_session_detail(username, sort_key)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    return record


@app.get("/api/admin/export")
async def admin_export(
    admin: str = Depends(verify_token),
    username: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    phrase_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Export filtered data as CSV download."""
    records = query_sessions(
        username=username,
        session_id=session_id,
        phrase_id=phrase_id,
        date_from=date_from,
        date_to=date_to,
    )

    # Enrich with phrase text lookup
    phrase_cache = {}
    all_phrases = get_all_phrases(include_inactive=True)
    for p in all_phrases:
        phrase_cache[p["phrase_id"]] = p.get("text", "")

    csv_content = build_csv(records, phrase_cache)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"keystroke_export_{timestamp}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ══════════════════════════════════════════════════════════════
# ADMIN — PHRASE MANAGEMENT
# ══════════════════════════════════════════════════════════════

@app.get("/api/admin/phrases")
async def admin_list_phrases(
    admin: str = Depends(verify_token),
    include_inactive: bool = Query(False),
):
    """List all phrases (admin view, includes inactive if requested)."""
    phrases = get_all_phrases(include_inactive=include_inactive)
    return {"phrases": phrases, "count": len(phrases)}


@app.post("/api/admin/phrases", status_code=201)
async def admin_create_phrase(
    body: PhraseCreateRequest,
    admin: str = Depends(verify_token),
):
    """Create a new typing phrase."""
    phrase = create_phrase(
        text=body.text,
        category=body.category,
        order=body.order,
        max_attempts=body.max_attempts,
        admin_user=admin,
    )
    return {"status": "created", "phrase": phrase}


@app.put("/api/admin/phrases/{phrase_id}")
async def admin_update_phrase(
    phrase_id: str,
    body: PhraseUpdateRequest,
    admin: str = Depends(verify_token),
):
    """Update an existing phrase (bumps version if text changes)."""
    updated = update_phrase(
        phrase_id=phrase_id,
        text=body.text,
        category=body.category,
        order=body.order,
        max_attempts=body.max_attempts,
        active=body.active,
        admin_user=admin,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Phrase not found")
    return {"status": "updated", "phrase": updated}


@app.delete("/api/admin/phrases/{phrase_id}")
async def admin_delete_phrase(
    phrase_id: str,
    hard: bool = Query(False),
    admin: str = Depends(verify_token),
):
    """Soft-delete (deactivate) or hard-delete a phrase."""
    if hard:
        success = hard_delete_phrase(phrase_id, admin_user=admin)
    else:
        success = delete_phrase(phrase_id, admin_user=admin)

    if not success:
        raise HTTPException(status_code=404, detail="Phrase not found")
    return {"status": "deleted", "phrase_id": phrase_id}


@app.post("/api/admin/phrases/seed")
async def admin_seed_phrases(admin: str = Depends(verify_token)):
    """Seed default phrases (only if table is empty)."""
    count = seed_default_phrases()
    return {"status": "seeded", "count": count}


# ══════════════════════════════════════════════════════════════
# ADMIN — AUDIT LOG
# ══════════════════════════════════════════════════════════════

@app.get("/api/admin/audit-log")
async def admin_audit_log(
    admin: str = Depends(verify_token),
    phrase_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Retrieve phrase change audit log."""
    logs = get_audit_logs(phrase_id=phrase_id, limit=limit)
    return {"logs": logs, "count": len(logs)}


# ── Health Check ───────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Mangum handler for AWS Lambda ──────────────────────────────
handler = Mangum(app, lifespan="off", api_gateway_base_path="/prod")
