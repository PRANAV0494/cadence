"""Append telemetry flushes to JSONL when CADENCE_DUMP_DIR is set.

Lab recapture only. Default demo behaviour is unchanged (env unset → no
files). Filenames are sanitised session ids, not participant names.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from provenance import MAX_EVENTS_PER_SESSION

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

# One flush can fill but never exceed what one session holds. Imported rather
# than a third hardcoded 10_000 alongside provenance.MAX_EVENTS_PER_SESSION and
# addon.MAX_EVENTS_PER_FLUSH — three copies documented as "the same bound" is
# three chances for them to stop being the same.
MAX_DUMP_EVENTS = MAX_EVENTS_PER_SESSION


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
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"events": events}, ensure_ascii=False) + "\n")
    except OSError as exc:
        # A full disk mid-capture used to pass silently, and the operator
        # would find the gap at analysis time. The rest of the addon reports
        # to stderr; do the same rather than swallow.
        print(f"cadence: telemetry dump failed for {path}: {exc}", file=sys.stderr)
        return None
    # Dumps inherit whole-document key/code including password boxes (see
    # docs/RECAPTURE.md consent).
    #
    # This is genuinely best-effort and on the documented target platform it
    # is close to nothing: the recapture procedure is PowerShell, and on
    # Windows os.chmod only toggles the read-only bit — it grants no ACL
    # protection against other users. The real controls are the gitignored
    # data/private/ location and full-disk encryption, which is what
    # docs/RECAPTURE.md tells participants.
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        print(f"cadence: could not restrict {path}: {exc}", file=sys.stderr)
    return path
