"""Session idle TTL. Pure functions, no mitmproxy.

A buffer that lives forever lets one browser's keystrokes justify a POST
hours later on a stolen cookie. Idle sessions are dropped; the next
request is a new empty session.
"""

from __future__ import annotations

# 30 minutes. Shorter than a workday, longer than a form.
TTL_SECONDS = 30 * 60


def expire(
    now: float,
    last_seen: dict[str, float],
    stores: list[dict],
    ttl: float = TTL_SECONDS,
) -> list[str]:
    """Remove keys idle longer than ttl from last_seen and every store.

    Returns the dropped session ids. `stores` are the addon dicts that
    are keyed by session (sessions, score, decisions, last_flags, blocks).
    """
    dropped = [
        key for key, seen in list(last_seen.items()) if now - seen > ttl
    ]
    for key in dropped:
        last_seen.pop(key, None)
        for store in stores:
            store.pop(key, None)
    return dropped


def touch(last_seen: dict[str, float], key: str, now: float) -> None:
    last_seen[key] = now
