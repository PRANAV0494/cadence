"""
End-to-end tests for the collection endpoint.

These cross the boundary the earlier bug hid behind. The capture SDK, the
transport schema and the feature extractor were fixed in three separate places
at three different times; nothing until now checked that a payload produced by
the real SDK survives the real endpoint.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "edge" / "cadence-sdk.js"


@pytest.fixture(scope="module")
def client():
    """
    TestClient with the environment the API refuses to start without.

    Assigned, not setdefault: a real JWT_SECRET_KEY exported in a developer's
    shell would otherwise be kept, making the suite depend on the machine it
    runs on. The hash is a syntactically valid bcrypt string so anything that
    parses it does not choke; no test logs in through it.
    """
    import os

    os.environ["JWT_SECRET_KEY"] = "test-key-not-used-for-real-tokens"
    os.environ["ADMIN_USERNAME"] = "test-admin"
    os.environ["ADMIN_PASSWORD_HASH"] = "$2b$12$" + "K" * 53
    os.environ["USE_LOCAL_DB"] = "true"

    from fastapi.testclient import TestClient

    import cadence.api.main as main

    return TestClient(main.app)


def sdk_events(script_body: str):
    """Drive the real capture SDK under Node and return its real output."""
    script = f"""
    const {{ createRecorder }} = require({json.dumps(str(SDK))});
    const r = createRecorder();
    let now = 0;
    performance.now = () => now;
    const advance = (ms) => {{ now += ms; }};
    const down = (code, key) => r.onKeyDown({{ code, key, repeat: false, isTrusted: true }});
    const up   = (code, key) => r.onKeyUp({{ code, key, isTrusted: true }});
    {script_body}
    process.stdout.write(JSON.stringify(r.getEvents()));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def payload(events, **over):
    body = {
        "username": "tester",
        "session_id": "11111111-2222-3333-4444-555555555555",
        "attempt_number": 1,
        "phrase_id": "p1",
        "phrase_version": 1,
        "events": events,
        "consent_given": True,
        "timestamp": "2026-08-23T12:00:00Z",
    }
    body.update(over)
    return body


needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to drive the SDK"
)


@needs_node
def test_real_sdk_payload_is_accepted(client):
    """The schema the SDK emits is the schema the API accepts."""
    events = sdk_events(
        """
        down('KeyH','h'); advance(90);  up('KeyH','h'); advance(110);
        down('KeyE','e'); advance(85);  up('KeyE','e'); advance(120);
        down('KeyY','y'); advance(100); up('KeyY','y');
        """
    )
    r = client.post("/api/submit", json=payload(events))

    assert r.status_code == 201, r.text
    assert r.json()["features_summary"]["typing_speed_wpm"] > 0


@needs_node
def test_modifier_keys_survive_transport_and_are_excluded_from_timing(client):
    """`is_modifier` must reach the extractor, or Shift re-inflates dwell."""
    events = sdk_events(
        """
        for (let i = 0; i < 4; i++) {
          down('ShiftLeft','Shift'); advance(40);
          down('KeyA','A');          advance(85);
          up('KeyA','A');            advance(195);
          up('ShiftLeft','Shift');
        }
        """
    )
    assert any(e["is_modifier"] for e in events)

    r = client.post("/api/submit", json=payload(events))
    assert r.status_code == 201, r.text

    # A 201 alone would also pass if is_modifier were dropped in transit and
    # the 320 ms Shift hold counted as a character. Assert on the numbers.
    summary = r.json()["features_summary"]
    # Four capitals typed over ~1.28 s: with Shift counted the character total
    # doubles and WPM roughly doubles with it.
    assert 0 < summary["typing_speed_wpm"] < 100, summary
    letters_only_wpm = (4 / 5.0) / (summary["total_duration_ms"] / 60000.0)
    assert abs(summary["typing_speed_wpm"] - letters_only_wpm) < 0.5, (
        f"WPM {summary['typing_speed_wpm']} does not match the four letter "
        f"presses ({letters_only_wpm:.2f}); modifiers are being counted."
    )


def test_legacy_key_index_payload_is_rejected(client):
    """
    A pre-fix client sends `key_index` and no `seq`. Its dwell times are
    unusable, so it must be refused rather than silently stored — which is
    exactly what happened to the first 293 collected sessions.
    """
    legacy = [
        {"event_type": "keydown", "key": "a", "timestamp": 0.0, "key_index": 0,
         "key_class": "letter", "is_backspace": False, "is_paste": False},
        {"event_type": "keyup", "key": "a", "timestamp": 90.0, "key_index": 1,
         "key_class": "letter", "is_backspace": False, "is_paste": False},
    ]
    r = client.post("/api/submit", json=payload(legacy))

    # Rejected at the schema boundary: unknown fields are forbidden.
    assert r.status_code == 422, r.text


def test_stream_without_seq_returns_422_not_500(client):
    """
    Events that parse but cannot be paired must surface as a client error.
    Called bare, extract_features raises and FastAPI would return 500.
    """
    unpairable = [
        {"event_type": "keydown", "key": "a", "code": "KeyA", "timestamp": 0.0},
        {"event_type": "keyup", "key": "a", "code": "KeyA", "timestamp": 90.0},
    ]
    r = client.post("/api/submit", json=payload(unpairable))

    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "unusable_event_stream"
    assert "cadence-sdk.js" in r.json()["detail"]["remedy"]


def test_unknown_event_type_is_rejected(client):
    bad = [{"event_type": "keypress", "key": "a", "code": "KeyA",
            "timestamp": 0.0, "seq": 0}]
    r = client.post("/api/submit", json=payload(bad))
    assert r.status_code == 422


def test_consent_is_required(client):
    r = client.post("/api/submit", json=payload([], consent_given=False))
    assert r.status_code == 400
    assert "consent" in r.json()["detail"].lower()


def test_empty_event_list_is_rejected(client):
    r = client.post("/api/submit", json=payload([]))
    assert r.status_code == 400


def test_legacy_payload_names_the_offending_fields(client):
    """
    Issue #3 asked that a pre-fix client be told to upgrade. extra="forbid"
    gives a schema 422; the detail must at least name key_index so the reader
    knows which field is the problem.
    """
    legacy = [
        {"event_type": "keydown", "key": "a", "timestamp": 0.0, "key_index": 0,
         "key_class": "letter", "is_backspace": False, "is_paste": False},
    ]
    r = client.post("/api/submit", json=payload(legacy))

    assert r.status_code == 422
    assert "key_index" in r.text


@needs_node
def test_paste_reaches_the_api_without_leaking_content(client):
    """The privacy invariant has to hold across the wire, not just in the SDK."""
    events = sdk_events(
        """
        down('KeyA','a'); advance(80); up('KeyA','a'); advance(50);
        r.onPaste({ clipboardData: { getData: () => 'super-secret-password' }, isTrusted: true });
        advance(40);
        down('KeyB','b'); advance(80); up('KeyB','b');
        """
    )
    body = payload(events)
    assert "super-secret-password" not in json.dumps(body)

    r = client.post("/api/submit", json=body)
    assert r.status_code == 201, r.text
    assert "super-secret-password" not in r.text
