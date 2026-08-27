"""Session idle TTL drops stale buffers."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "edge"))

from ttl import TTL_SECONDS, expire, touch  # noqa: E402


def test_idle_session_is_dropped():
    last = {}
    sessions = {"a": [{"event_type": "keydown"}]}
    score = {"a": 1.2}
    touch(last, "a", 0.0)
    dropped = expire(TTL_SECONDS + 1, last, [sessions, score])
    assert dropped == ["a"]
    assert sessions == {}
    assert score == {}
    assert last == {}


def test_fresh_session_is_kept():
    last = {}
    sessions = {"a": [1]}
    touch(last, "a", 100.0)
    dropped = expire(100.0 + 10, last, [sessions], ttl=30)
    assert dropped == []
    assert "a" in sessions
