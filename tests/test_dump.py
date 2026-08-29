"""CADENCE_DUMP_DIR writes JSONL flushes; unset env writes nothing."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "edge"))

from dump import append_flush, filename  # noqa: E402


def test_filename_strips_connection_fallback_punctuation():
    assert filename(r"127.0.0.1|(1, 2)") == "127.0.0.1_1_2.jsonl"


def test_append_flush_writes_eval_shaped_jsonl(tmp_path):
    events = [{"event_type": "keydown", "seq": 0, "key": "a", "timestamp": 1.0}]
    path = append_flush("abc", events, dest=tmp_path)
    assert path == tmp_path / "abc.jsonl"
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line == {"events": events}


def test_append_flush_noops_without_dest(monkeypatch, tmp_path):
    monkeypatch.delenv("CADENCE_DUMP_DIR", raising=False)
    assert append_flush("abc", [{"event_type": "keydown"}]) is None
    assert list(tmp_path.iterdir()) == []
