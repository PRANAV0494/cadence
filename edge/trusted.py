"""Trust flag on capture events.

The SDK records `is_trusted` from the browser (`event.isTrusted`). Scripted
keydowns (element.dispatchEvent, many automation fills) are untrusted.
Missing the field is treated as trusted so older fixtures still replay.
"""

from __future__ import annotations


def is_trusted(event: dict) -> bool:
    """False only when the event explicitly says it is not trusted."""
    return event.get("is_trusted", True) is not False
