#!/usr/bin/env python3
"""
Verify that every measured number quoted in the documentation matches
evaluation/results.json.

WHY THIS EXISTS
---------------
A fabricated statistic once travelled from a notebook into a CV and onto a
public profile, and stayed there for months, because nothing connected the claim
to the computation that supposedly produced it. The number was p = 4.7e-21, from
a cell that t-tested a vector against itself scaled by 1.1.

CONTRIBUTING.md asks for measurement honesty. This makes it mechanical.

HOW CLAIMS ARE MARKED
---------------------
    The best result is <!--@cmu_lof_eer-->0.1367<!--/--> on 51 subjects.

The marker names a key in results.json. results.json stores each number at
**full measured precision**; a document may display it rounded, and the
comparison rounds the declared value to however many decimals the document
shows. So results.json holds 3.1127 while the README honestly shows 3.11.

The whole displayed number must sit inside the markers. Writing
`<!--@key-->3.11<!--/-->27` to render 3.1127 while verifying only 3.11 is
rejected — the first version of this checker was defeated exactly that way.

WHAT IT CHECKS
--------------
1. Provenance — every result has a source that resolves, a description, and a
   sample count.
2. Agreement — every marked claim matches its declared value at the shown
   precision.
3. No digits smuggled immediately outside a marker.
4. No document asserts a retracted value outside a retraction notice.
5. No malformed markers silently verifying nothing.

A NOTE ON THE ESCAPE HATCH
--------------------------
<!--!retracted--> is honour-system: wrapping a live assertion in it hides the
number from this checker while still rendering it to readers. That is inherent
to any escape hatch. The mitigation is that the wrapper is loud in a diff, which
is where a reviewer will see it.

Usage:
    python evaluation/check_docs.py          # check; exit 1 on any problem
    python evaluation/check_docs.py --list   # print declared results
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results.json"

# Every markdown file is scanned. A hardcoded list is how the retracted p-value
# survived in docs/ while the checker looked only at three other files.
DOC_GLOB = "**/*.md"
# Matched against any path segment, so nested reference/ dirs are excluded too.
DOC_EXCLUDE_PARTS = {".git", "node_modules", "reference"}
DOC_EXCLUDE_PREFIXES = ("tests/legacy/",)

# <!--@key-->  shown text  <!--/-->
CLAIM = re.compile(r"<!--@([A-Za-z0-9_]+)-->(.*?)<!--/-->", re.DOTALL)
CLAIM_OPEN = "<!--@"

# Retracted values stay quotable inside the documents that retract them,
# otherwise the only way to pass CI is to delete the record of the mistake.
RETRACTION_NOTICE = re.compile(r"<!--!retracted-->.*?<!--/-->", re.DOTALL)
RETRACTION_OPEN = "<!--!retracted-->"

RETRACTED = {
    "4.689064502037325e-21": "degenerate t-test (vector against itself scaled by 1.1)",
    "4.689e-21": "degenerate t-test (vector against itself scaled by 1.1)",
    "4.7e-21": "degenerate t-test (vector against itself scaled by 1.1)",
}

# Sources that legitimately do not resolve to a path in this repository:
# published work, and files excluded from version control.
EXTERNAL_PREFIXES = ("external:", "private:")


def load_results() -> dict:
    if not RESULTS.exists():
        sys.exit(f"missing {RESULTS.relative_to(ROOT)}")
    return json.loads(RESULTS.read_text(encoding="utf-8"))["results"]


def load_docs(root: Path = ROOT) -> dict[str, str]:
    docs: dict[str, str] = {}
    for path in sorted(root.glob(DOC_GLOB)):
        rel = path.relative_to(root).as_posix()
        if set(Path(rel).parts) & DOC_EXCLUDE_PARTS:
            continue
        if rel.startswith(DOC_EXCLUDE_PREFIXES):
            continue
        docs[rel] = path.read_text(encoding="utf-8")
    return docs


def check_provenance(results: dict, root: Path = ROOT) -> list[str]:
    """A number without a traceable source is an assertion, not a result."""
    problems: list[str] = []
    for key, r in results.items():
        if "value" not in r:
            problems.append(f"{key}: no 'value'")
        if not r.get("description"):
            problems.append(f"{key}: no 'description'")

        source = r.get("source")
        if not source:
            problems.append(f"{key}: no 'source' — cannot be traced to a computation")
        elif not source.startswith(EXTERNAL_PREFIXES):
            target = root / source.split("#", 1)[0]  # strip an anchor like #cell-11
            if not target.exists():
                problems.append(
                    f"{key}: source {source!r} does not exist. Prefix with "
                    f"'external:' or 'private:' if it is not a file in this repo."
                )

        # A counting unit describes a population; every other result needs an n.
        if r.get("unit") != "people" and not any(k.startswith("n_") for k in r):
            problems.append(f"{key}: no sample count (n_subjects / n_rows)")
    return problems


# Characters that change a number's value if they sit just outside a marker.
# Leading: '9' before 0.1367 renders 90.1367; '-' flips the sign; '1.' makes
# 0.1367 into 1.0.1367. A bare '.' cannot extend a number leftwards.
SMUGGLE_BEFORE = re.compile(r"(?:[\d+\-−]|\d\.)\Z")  # \Z, not $: $ also matches before a trailing newline
# Trailing: more digits, a decimal point *followed by* a digit, an exponent, or
# a percent sign. A lone '.' is sentence punctuation, not smuggling.
SMUGGLE_AFTER = re.compile(r"^(?:\d|\.\d|[eE][-+]?\d|%)")


def _shown_number(text: str) -> tuple[float, int, bool] | None:
    """
    Return (value, decimals displayed, is_scientific) for the number in `text`.

    For e-notation, `decimals` counts mantissa digits, and the comparison
    formats the declared value to that precision instead of calling round().
    round(1.23e-05, 0) is 0.0, which failed every scientific claim including
    exact matches; formatting keeps the "documents may round" contract intact
    for the tiny p-values most likely to use this notation.
    """
    cleaned = text.strip().replace(",", "").replace("−", "-").replace("**", "")
    m = re.search(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", cleaned)
    if not m:
        return None
    literal = m.group()
    scientific = "e" in literal.lower()
    mantissa = literal.lower().split("e")[0] if scientific else literal
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    return float(literal), decimals, scientific


def check_claims(results: dict, docs: dict[str, str]) -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0

    for rel, text in docs.items():
        # A marker that never matched the pattern verifies nothing, silently.
        complete = len(CLAIM.findall(text))
        if text.count(CLAIM_OPEN) != complete:
            problems.append(
                f"{rel}: malformed claim marker — {text.count(CLAIM_OPEN)} "
                f"'{CLAIM_OPEN}' but {complete} complete claims. Check for a "
                f"missing or misspelled <!--/-->."
            )
        if text.count(RETRACTION_OPEN) != len(RETRACTION_NOTICE.findall(text)):
            problems.append(f"{rel}: malformed retraction marker — missing <!--/-->.")

        asserted = RETRACTION_NOTICE.sub("", text)
        for bad, why in RETRACTED.items():
            if bad in asserted:
                problems.append(
                    f"{rel}: asserts retracted value {bad} — {why}. If documenting "
                    f"the retraction, wrap it in <!--!retracted-->...<!--/-->."
                )
                break  # one report per document is enough

        for match in CLAIM.finditer(text):
            key, shown = match.group(1), match.group(2)
            line = text[: match.start()].count("\n") + 1
            checked += 1

            if key not in results:
                problems.append(f"{rel}:{line}: claims '{key}', not in results.json")
                continue

            # Characters just outside the markers render but are not verified.
            # Both sides matter: '9' before, or '27' / 'e-21' / '%' after.
            # Two characters, so a digit-then-dot prefix like "1." is visible.
            leading = text[max(0, match.start() - 2) : match.start()]
            trailing = text[match.end() : match.end() + 12]
            if SMUGGLE_BEFORE.search(leading):
                problems.append(
                    f"{rel}:{line}: claim '{key}' is preceded by {leading!r}. "
                    f"The whole displayed number must be inside the markers."
                )
            if SMUGGLE_AFTER.match(trailing):
                problems.append(
                    f"{rel}:{line}: claim '{key}' is followed by {trailing[:6]!r}. "
                    f"The whole displayed number must be inside the markers."
                )

            parsed = _shown_number(shown)
            if parsed is None:
                problems.append(f"{rel}:{line}: claim '{key}' has no number in {shown!r}")
                continue
            found, decimals, scientific = parsed

            declared = float(results[key]["value"])

            is_percent = results[key].get("unit") == "percent"
            if is_percent:
                # A percent result may be written 85% or 0.85, but the form must
                # match the display: '0.85%' is wrong by 100x and must not pass.
                as_percent = "%" in shown or "percent" in shown.lower()
                candidates = {declared} if as_percent else {declared / 100}
            else:
                candidates = {declared}

            tol = max(1e-12, abs(found) * 1e-9)
            if scientific:
                # Format to the mantissa precision shown, so 1.2345e-05 may be
                # displayed as 1.23e-05 exactly as decimals may be rounded.
                ok = any(
                    abs(float(f"{c:.{decimals}e}") - found) <= max(tol, abs(c) * 1e-9)
                    for c in candidates
                )
            else:
                # The document may round the declared value; it may not disagree.
                ok = any(abs(round(c, decimals) - found) <= tol for c in candidates)

            if not ok:
                if is_percent and abs(found - declared) <= tol:
                    # Numerically equal but the wrong form — say so, rather than
                    # reporting two identical numbers as a mismatch.
                    problems.append(
                        f"{rel}:{line}: claim '{key}' is a percent result shown "
                        f"as bare {found}. Write '{declared:g}%' or "
                        f"'{declared / 100:g}' so the form is unambiguous."
                    )
                else:
                    problems.append(
                        f"{rel}:{line}: claim '{key}' shows {found}, "
                        f"results.json says {declared}"
                    )

    return problems, checked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="print declared results")
    args = ap.parse_args()

    results = load_results()

    if args.list:
        for key, r in sorted(results.items()):
            n = next((f"n={r[k]}" for k in r if k.startswith("n_")), "")
            print(f"{key:45s} {str(r['value']):>12} {n:12s} {r['source']}")
        return 0

    docs = load_docs()
    claim_problems, checked = check_claims(results, docs)
    problems = check_provenance(results) + claim_problems

    if problems:
        print("Documentation does not match measured results:\n")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nFix the document, or re-run the computation and update "
            "evaluation/results.json from its output.\n"
            "Do not edit results.json to make a document pass."
        )
        return 1

    print(f"OK — {checked} claims across {len(docs)} documents match results.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
