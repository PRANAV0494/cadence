"""HTTP malice detector: URL path/query and POST body only.

Headers are deliberately out of scope - Accept, User-Agent and
Content-Type carry no injection channel worth policing here, and
scanning them produces false positives on perfectly ordinary requests
(Accept: */* is the browser default, not an attacker signature).

What is checked: well-known lexical attack patterns in the URL and the
body - SQL injection probes, XSS payloads, path traversal, template
and command injection markers. This is lexical triage for the fusion
walk, not a WAF: the output is a signal, and the SPRT bounds decide.

No CICIDS vectors are used or claimed; the patterns below are the
canonical public payloads any injection tutorial starts with.
"""

from __future__ import annotations

import re

PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("sqli",
     re.compile(
         r"(?:'|--)\s*(?:or|and)\s+[\w']+\s*="
         r"|\bunion\b\s+(?:all\s+)?\bselect\b"
         r"|;\s*drop\s+table\b"
         r"|\bsleep\s*\(\s*\d+\s*\)"
         r"|\bwaitfor\s+delay\b",
         re.IGNORECASE,
     )),
    ("xss",
     re.compile(
         r"<\s*script\b"
         r"|on(?:error|load|click|mouseover)\s*="
         r"|javascript\s*:"
         r"|<\s*img\b[^>]*\bsrc\b",
         re.IGNORECASE,
     )),
    ("traversal",
     re.compile(
         r"(?:\.\./|\.\.\.\.\.|%2e%2e%2f)"
         r"|(?:/etc/(?:passwd|shadow))",
         re.IGNORECASE,
     )),
    ("template",
     re.compile(
         r"\{\{.*?\}\}"
         r"|\$\{.*?\}"
         r"|<%=.*?%>",
         re.IGNORECASE,
     )),
    ("command",
     re.compile(
         r";\s*(?:cat|rm|wget|curl|nc|bash|sh)\b"
        r"|\|\|\s*(?:cat|rm|wget|curl|nc|bash|sh)\b"
         r"|`[^`]*`",
         re.IGNORECASE,
     )),
)


def suspicious(url: str, body: bytes | None = None) -> str | None:
    """The first matching category for the URL (path+query) and body, or None.

    Pure string triage. None means "nothing matched" - never "clean for
    sure".
    """
    text = url or ""
    if body:
        try:
            text += " " + body.decode("utf-8", errors="replace")
        except Exception:
            pass
    for name, pattern in PATTERNS:
        if pattern.search(text):
            return name
    return None
