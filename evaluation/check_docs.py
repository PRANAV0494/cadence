#!/usr/bin/env python3
"""
Verify that every measured number quoted in the documentation matches
evaluation/results.json.

WHY THIS EXISTS
---------------
A fabricated statistic once travelled from a notebook onto this author's live
public profile, because nothing connected the claim to the computation that
supposedly produced it. The number was p = 4.7e-21, from a notebook cell that
t-tested a vector against itself scaled by 1.1 — arithmetic, not evidence.

It was caught about half an hour later, by an audit of the author's own prior
work, and retracted the same hour. Half an hour is luck. Nothing in the pipeline
would have stopped it, and nothing would have flagged it on day ninety either.
This file is what replaces the luck.

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
# published work, files excluded from version control, and values computed from
# other declared results. "derived:" must name those results, so a computed
# number still points somewhere checkable instead of citing this file itself.
EXTERNAL_PREFIXES = ("external:", "private:", "derived:")
DERIVED_PREFIX = "derived:"


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
        elif source.startswith(DERIVED_PREFIX):
            names = [n.strip() for n in source[len(DERIVED_PREFIX):].split(",") if n.strip()]
            if not names:
                problems.append(f"{key}: 'derived:' names no source results")
            for n in names:
                if n not in results:
                    problems.append(f"{key}: derived from {n!r}, which is not a result")
        elif source.startswith(EXTERNAL_PREFIXES):
            # An 'external:' or 'private:' marker with nothing after it is not
            # provenance, it is an opt-out from the check.
            if not source.split(":", 1)[1].strip():
                problems.append(f"{key}: source {source!r} has no detail after the prefix")
        else:
            target = root / source.split("#", 1)[0]  # strip an anchor like #cell-11
            if not target.exists():
                problems.append(
                    f"{key}: source {source!r} does not exist. Prefix with "
                    f"'external:' or 'private:' if it is not a file in this repo."
                )

        # A counting unit describes a population; every other result needs an n.
        counts = {k: v for k, v in r.items() if k.startswith("n_")}
        if r.get("unit") != "people" and not counts:
            problems.append(f"{key}: no sample count (n_subjects / n_rows)")
        for name, n in counts.items():
            # n_subjects: 0 or null satisfied a presence check while telling the
            # reader nothing. A sample count has to be a positive number.
            if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                problems.append(f"{key}: {name} is {n!r}; a sample count must be a positive integer")
    return problems


# Characters that change a number's value if they sit just outside a marker.
# Leading: '9' before 0.1367 renders 90.1367; '-' flips the sign; '1.' makes
# 0.1367 into 1.0.1367. A bare '.' cannot extend a number leftwards.
SMUGGLE_BEFORE = re.compile(r"(?:[\d+\-−]|\d\.)\Z")  # \Z, not $: $ also matches before a trailing newline
# Trailing: more digits, a decimal point *followed by* a digit, an exponent, or
# a percent sign. A lone '.' is sentence punctuation, not smuggling.
SMUGGLE_AFTER = re.compile(r"^(?:\d|\.\d|[eE][-+]?\d|%)")


# Wrappers a claim may legitimately carry: bold/italic/code emphasis, and the
# units or symbols that surround a number in prose.
_ALLOWED_WRAPPERS = re.compile(r"[*_`\s%]|&nbsp;|ms\b|percent\b", re.IGNORECASE)
# Anything comment-shaped inside a marker body is stripped before rendering, so
# digits hidden behind it are displayed but were never compared.
_ANY_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_ENTITY = re.compile(r"&#x?[0-9a-fA-F]+;|&[a-zA-Z]+;")


def _render_with_retraction_cover(text: str) -> tuple[str, list[bool]]:
    """
    Return the text as a reader sees it, plus a per-character flag for whether
    that character sits inside a retraction span.

    Comment *markers* are invisible; the text between them is not. So
    `4.7e-2<!--!retracted-->1<!--/-->` renders as `4.7e-21` — the digit inside
    the span is displayed. Deleting whole spans hid that: the literal never
    formed, so the check passed while readers saw a live retracted value.

    A mention is legitimate only when the entire literal is covered by a span,
    which is what wrapping is supposed to mean.
    """
    rendered: list[str] = []
    covered: list[bool] = []
    inside = False
    pos = 0

    for m in _ANY_COMMENT.finditer(text):
        chunk = text[pos : m.start()]
        rendered.append(chunk)
        covered.extend([inside] * len(chunk))

        token = m.group()
        if token.startswith(RETRACTION_OPEN):
            inside = True
        elif token == "<!--/-->":
            inside = False
        pos = m.end()

    tail = text[pos:]
    rendered.append(tail)
    covered.extend([inside] * len(tail))
    return "".join(rendered), covered


def _uncovered_retracted(text: str) -> list[str]:
    """Retracted literals that render without being fully inside a span."""
    rendered, covered = _render_with_retraction_cover(text)
    found = []
    for bad in RETRACTED:
        for m in re.finditer(re.escape(bad), rendered):
            if not all(covered[m.start() : m.end()]):
                found.append(bad)
                break
    return found


def _body_is_only_a_number(text: str) -> bool:
    """
    True when the marker body renders as exactly one number.

    Taking the first number substring was not enough. These all render 3.1127
    while only 3.11 was compared:

        <!--@t-->3.11<!--x-->27<!--/-->
        <!--@t-->3.11<!---->27<!--/-->
        <!--@t-->3.11&#50;7<!--/-->

    That is the precision-smuggling defect again, moved inside the span. The
    body must contain a number and nothing else that can render as one.
    """
    if _ANY_COMMENT.search(text) or _HTML_ENTITY.search(text):
        return False
    stripped = _ALLOWED_WRAPPERS.sub("", text.replace("−", "-"))
    return bool(re.fullmatch(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", stripped))


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

        # Compare against what renders, and require the whole literal to sit
        # inside a retraction span. Wrapping only a fragment --
        # `p = 4.7e-2<!--!retracted-->1<!--/-->` -- displays the live value with
        # no visible marker.
        for bad in _uncovered_retracted(text):
            problems.append(
                f"{rel}: renders retracted value {bad} — {RETRACTED[bad]}. Wrap "
                f"the whole literal in <!--!retracted-->...<!--/-->, not part of it."
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

            if not _body_is_only_a_number(shown):
                problems.append(
                    f"{rel}:{line}: claim '{key}' body {shown!r} is not a plain "
                    f"number. Comments or entities inside a marker render digits "
                    f"that are never compared."
                )
                continue

            parsed = _shown_number(shown)
            if parsed is None:
                problems.append(f"{rel}:{line}: claim '{key}' has no number in {shown!r}")
                continue
            found, decimals, scientific = parsed

            raw = results[key].get("value")
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                problems.append(
                    f"{rel}:{line}: claim '{key}' has a non-numeric value "
                    f"({raw!r}) in results.json"
                )
                continue
            declared = float(raw)

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
