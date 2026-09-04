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

# One flush can fill but never exceed what one session holds (same bound as
# the proxy's per-session cap). Keeps a rogue 10 MB body from becoming a
# 10 MB file append even before the proxy-side flush cap runs.
MAX_DUMP_EVENTS = 10_000


def dump_dir() -> Path | None:
    raw = os.environ.get("CADENCE_DUMP_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def filename(session_id: str) -> str:
    # Sanitization can collide on adversarial inputs (a|b vs a/b -> a_b);
    # fine for lab recapture where sids are proxy-minted hex.
    stem = _SAFE.sub("_", session_id)
    stem = re.sub(r"_+", "_", stem).strip("._") or "session"
    return f"{stem}.jsonl"


def append_flush(session_id: str, events: list[dict], dest: Path | None = None) -> Path | None:
    """Write one `{"events": [...]}` line. No-op if dumping is off."""
    root = dest if dest is not None else dump_dir()
    if root is None or not events:
        return None
    if len(events) > MAX_DUMP_EVENTS:
        events = events[-MAX_DUMP_EVENTS:]
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename(session_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"events": events}, ensure_ascii=False) + "\n")
    # Dumps inherit whole-document key/code including password boxes (see
    # docs/RECAPTURE.md consent). Restrict new files best-effort; the lab
    # dir itself must still live under gitignored data/private/.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
