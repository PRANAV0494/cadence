"""
Contract tests across the client/server boundary.

Every other test in this suite hand-builds event dicts, which means they assert
what the extractor does with events we *believe* the SDK emits. That is the same
blind spot that let the original defect ship: docs/feature_verification.md marked
the pairing logic "correct" after auditing the Python in isolation, never
checking what the browser actually put in those fields.

These tests run the real SDK under Node, feed its real output to the real
extractor, and assert on the result. If a field is renamed on either side, they
fail.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cadence.features.keystroke import extract_features

SDK = Path(__file__).resolve().parents[1] / "edge" / "cadence-sdk.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required for SDK contract tests"
)


def run_sdk(script_body: str):
    """Drive the SDK in Node and return the events it recorded."""
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
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, f"node failed: {out.stderr}"
    return json.loads(out.stdout)


def test_sdk_output_is_accepted_by_the_extractor():
    """The schemas agree. This is the test that was missing."""
    events = run_sdk(
        """
        down('KeyH','h'); advance(90);  up('KeyH','h'); advance(110);
        down('KeyE','e'); advance(85);  up('KeyE','e'); advance(120);
        down('KeyY','y'); advance(100); up('KeyY','y');
        """
    )
    feats = extract_features(events)

    dwell = feats["core_features"]["per_key_dwell_times"]
    assert dwell == [90.0, 85.0, 100.0]
    assert feats["variability_features"]["mean_dwell_time"] > 0
    assert feats["distribution_features"]["min_dwell_time"] > 0


def test_shift_does_not_inflate_dwell_or_typing_speed():
    """
    Regression for the defect this PR's review caught.

    Shift is held 320 ms across a letter held 85 ms. Before the is_modifier
    flag, mean dwell came out at 202.5 ms instead of 85.0 and WPM roughly
    doubled, because Shift counted as a typed character.
    """
    events = run_sdk(
        """
        for (let i = 0; i < 4; i++) {
          down('ShiftLeft','Shift'); advance(40);
          down('KeyA','A');          advance(85);
          up('KeyA','A');            advance(195);
          up('ShiftLeft','Shift');   advance(180);
        }
        """
    )
    feats = extract_features(events)

    assert all(e["is_modifier"] is True for e in events if e["key"] == "Shift")
    # Only the four letter presses contribute.
    assert feats["core_features"]["per_key_dwell_times"] == [85.0] * 4
    assert feats["variability_features"]["mean_dwell_time"] == 85.0
    # Digraphs are letter-to-letter, not Shift-to-letter.
    assert all(
        "Shift" not in pair
        for pair in feats["digraph_features"]["digraph_latencies"]
    )


def test_rollover_survives_the_round_trip():
    """Overlapping presses pair correctly through real SDK output."""
    events = run_sdk(
        """
        down('KeyA','a'); advance(100);
        down('KeyB','b'); advance(50);
        up('KeyA','a');   advance(30);
        up('KeyB','b');
        """
    )
    feats = extract_features(events)

    # A: 0 -> 150 = 150.  B: 100 -> 180 = 80.
    assert feats["core_features"]["per_key_dwell_times"] == [150.0, 80.0]


def test_autorepeat_is_not_counted_as_new_presses():
    events = run_sdk(
        """
        const rep = (code, key) => r.onKeyDown({ code, key, repeat: true, isTrusted: true });
        down('KeyA','a'); advance(50);
        rep('KeyA','a');  advance(50);
        rep('KeyA','a');  advance(50);
        up('KeyA','a');
        """
    )
    keydowns = [e for e in events if e["event_type"] == "keydown"]

    assert len(keydowns) == 1
    assert extract_features(events)["core_features"]["per_key_dwell_times"] == [150.0]


def test_paste_records_length_only_never_content():
    """Privacy invariant: pasted text must not appear anywhere in telemetry."""
    events = run_sdk(
        """
        r.onPaste({ clipboardData: { getData: () => 'super-secret-password' }, isTrusted: true });
        """
    )
    blob = json.dumps(events)

    assert "super-secret-password" not in blob
    assert events[0]["pasted_length"] == len("super-secret-password")
    assert events[0]["is_paste"] is True


def test_untrusted_events_are_marked():
    """Synthetic input must be distinguishable downstream."""
    script = """
    r.onKeyDown({ code: 'KeyA', key: 'a', repeat: false, isTrusted: false });
    r.onKeyUp({ code: 'KeyA', key: 'a', isTrusted: false });
    """
    events = run_sdk(script)

    assert all(e["is_trusted"] is False for e in events)


def test_non_character_keys_are_flagged_by_the_sdk_itself():
    """
    The finding was that the SDK set is_modifier: false on Tab, Escape, arrows
    and F-keys, so they entered dwell, typing speed and digraphs. An extractor
    test that hand-sets the flag proves nothing about that — it has to come
    from cadence-sdk.js.
    """
    events = run_sdk(
        """
        down('Tab','Tab');             advance(140); up('Tab','Tab');       advance(60);
        down('Escape','Escape');       advance(130); up('Escape','Escape'); advance(60);
        down('ArrowLeft','ArrowLeft'); advance(120); up('ArrowLeft','ArrowLeft'); advance(60);
        down('F1','F1');               advance(150); up('F1','F1');         advance(60);
        down('KeyA','a');              advance(85);  up('KeyA','a');
        """
    )
    flags = {e["key"]: e["is_modifier"] for e in events if e["event_type"] == "keydown"}
    assert flags == {"Tab": True, "Escape": True, "ArrowLeft": True, "F1": True, "a": False}

    feats = extract_features(events)
    # Only the letter contributes; the long non-character holds are excluded.
    assert feats["core_features"]["per_key_dwell_times"] == [85.0]
    assert all("Tab" not in p and "F1" not in p
               for p in feats["digraph_features"]["digraph_latencies"])
