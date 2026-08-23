#!/usr/bin/env python3
"""
Fail if the SAM template gives a secret parameter a Default.

A CloudFormation `Default` is shipped by `sam deploy` when no override is
passed. That is how this deployment's JWT signing key came to be a string
published in the repository — every admin token was signed with it.

The first guard grepped for the two literals that had already been removed,
which checks for yesterday's mistake rather than the defect class. It also
treated a missing template as a pass, because grep exits 2 and `if` reads a
non-zero exit as false.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATE = Path("deploy/template.yaml")

# Any parameter whose value must never be baked into the template.
SECRET_PARAMETERS = ("JwtSecretKey", "AdminUsername", "AdminPasswordHash")


def parameters_with_defaults(text: str, names=SECRET_PARAMETERS) -> list[str]:
    """Names among `names` that declare a Default in their parameter block."""
    offenders = []
    for name in names:
        block = re.search(rf"^  {re.escape(name)}:\n((?:    .*\n|\n)*)", text, re.MULTILINE)
        if block and re.search(r"^    Default:", block.group(1), re.MULTILINE):
            offenders.append(name)
    return offenders


def main() -> int:
    if not TEMPLATE.exists():
        print(f"::error::{TEMPLATE} is missing. A deleted template must not pass.")
        return 1

    offenders = parameters_with_defaults(TEMPLATE.read_text(encoding="utf-8"))
    if offenders:
        print(
            f"::error::Secret parameters carry a Default: {', '.join(offenders)}. "
            f"sam deploy without an override would ship it."
        )
        return 1

    print("OK — no Default on any secret parameter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
