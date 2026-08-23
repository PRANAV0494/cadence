#!/usr/bin/env python3
"""
Fail if a tracked file appears to contain a hardcoded credential.

WHY THIS IS A MODULE AND NOT A SHELL LINE IN ci.yml
---------------------------------------------------
The first version was a `git grep` regex that matched only ALL-CAPS names with
double-quoted values, so single-quoted and unquoted assignments passed. The
rewrite lived inside the workflow as an embedded heredoc, which had two costs:
it could not be imported by a test, and a local "verification" that retyped the
logic into a scratch script passed while the workflow itself was still broken.

So the scanner is ordinary Python with ordinary tests. CI runs this file; the
tests import this file. There is nothing to keep in sync.

WHAT COUNTS AS A HIT
--------------------
A secret-shaped name assigned a literal value. The decision is made on the
**value**, not the line: skipping a whole line because it contained the word
"example" or an HTML tag meant a real key on that line was invisible.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Documentation about secrets discusses them by name; that is not a leak.
SKIP_PREFIXES = ("docs/", "CONTRIBUTING.md", "MANIFEST.md", "scripts/check_secrets.py")
SKIP_EXACT = {".env.example"}

NAMES = (
    r"(?:JWT_SECRET_KEY|JwtSecretKey|ADMIN_PASSWORD_HASH|AdminPasswordHash"
    r"|[A-Za-z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[A-Za-z0-9_]*)"
)
# A literal value: quoted either way, or bare. Brackets are excluded so the
# match stops at "(" or "[", which is what lets a call or subscript be told
# apart from a literal by looking at the next character.
VALUE = r"""(?:"[^"\n]{8,}"|'[^'\n]{8,}'|[^\s"'#,()\[\]{}]{8,})"""
ASSIGN = re.compile(rf"{NAMES}\s*[:=]\s*({VALUE})")

# Shapes that are secrets regardless of the name beside them.
STANDALONE = re.compile(
    r"change-me-in-produc[t]ion"       # bracket: stops this file self-matching
    r"|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)

# Applied to the *value only*. A placeholder is not a credential; a real key
# that merely shares a line with the word "example" still is.
PLACEHOLDER = re.compile(
    r"^\$\{|^<.*>$|^%[A-Z_]+%$"          # ${VAR}, <your-key>, %TOKEN%
    r"|example|placeholder|changeme|dummy|redacted|sample"
    r"|^x{4,}$|^\.{3,}$|^your[-_]|^my[-_]|^test[-_]key",
    re.IGNORECASE,
)


def _is_reference(line: str, match: re.Match) -> bool:
    """True when the "value" is really a call or subscript: a config read."""
    return line[match.end() : match.end() + 1] in ("(", "[")


def scan_line(line: str) -> bool:
    """True if this line looks like it hardcodes a secret."""
    if STANDALONE.search(line):
        value_ctx = line
        # Even a standalone shape can be an illustration.
        return not PLACEHOLDER.search(value_ctx)

    m = ASSIGN.search(line)
    if not m or _is_reference(line, m):
        return False

    value = m.group(1).strip("\"'")
    if not value or PLACEHOLDER.search(value):
        return False
    return True


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return out.stdout.split()


def scan_repo(files: list[str] | None = None) -> list[str]:
    hits: list[str] = []
    for f in files if files is not None else tracked_files():
        if f.startswith(SKIP_PREFIXES) or f in SKIP_EXACT:
            continue
        try:
            text = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if scan_line(line):
                hits.append(f"{f}:{n}: {line.strip()[:120]}")
    return hits


def main() -> int:
    hits = scan_repo()
    if hits:
        print("::error::Possible hardcoded credential:")
        print("\n".join(hits))
        print(
            "\nConfiguration comes from the environment. If this is a "
            "placeholder, make it look like one (<your-key>, ${VAR}, xxxx)."
        )
        return 1
    print("OK — no hardcoded credentials in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
