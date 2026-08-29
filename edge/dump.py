"""Append telemetry flushes to JSONL when CADENCE_DUMP_DIR is set.

Lab recapture only. Default demo behaviour is unchanged (env unset → no
files). Filenames are sanitised session ids, not participant names.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def dump_dir() -> Path | None:
    raw = os.environ.get("CADENCE_DUMP_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def filename(session_id: str) -> str:
    stem = _SAFE.sub("_", session_id)
    stem = re.sub(r"_+", "_", stem).strip("._") or "session"
    return f"{stem}.jsonl"


def append_flush(session_id: str, events: list[dict], dest: Path | None = None) -> Path | None:
    """Write one `{"events": [...]}` line. No-op if dumping is off."""
    root = dest if dest is not None else dump_dir()
    if root is None or not events:
        return None
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename(session_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"events": events}, ensure_ascii=False) + "\n")
    return path
