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

CONTRIBUTING.md asks for measurement honesty. This makes it mechanical: a
document cannot quote a result that is not in results.json with a matching
value, and a result cannot silently change without every document that cites it
failing CI.

WHAT IT CHECKS
--------------
1. Every result in results.json carries provenance — a source, a description,
   and a sample count where one is meaningful.
2. Every number in a documented claim matches a declared result. Claims are
   marked inline so prose and tables are both covered:

       The best result is <!--@cmu_lof_eer-->0.1367<!--/--> on 51 subjects.

   The marker names a key; the text between the markers must equal that key's
   value. Formatting is flexible (0.1367, .1367, 13.67% for percent units) but
   the underlying number must agree.
3. No document quotes the retracted p-value.

Usage:
    python evaluation/check_docs.py            # check, exit 1 on mismatch
    python evaluation/check_docs.py --list     # print declared results
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results.json"
DOCS = ["README.md", "CONTRIBUTING.md", "notebooks/exploration/README.md"]

# <!--@key-->  visible text  <!--/-->
CLAIM = re.compile(r"<!--@([a-z0-9_]+)-->(.*?)<!--/-->", re.DOTALL)

# Retracted values must still be quotable in the documents that retract them,
# otherwise the only way to pass CI is to delete the record of the mistake —
# which is the opposite of what this check is for. Wrapping marks the mention as
# a warning rather than an assertion:
#
#     <!--!retracted-->p = 4.7e-21<!--/-->
RETRACTION_NOTICE = re.compile(r"<!--!retracted-->.*?<!--/-->", re.DOTALL)

# Numbers that must never reappear: retracted or known-fabricated.
RETRACTED = {
    "4.7e-21": "degenerate t-test (vector against itself scaled by 1.1)",
    "4.689e-21": "degenerate t-test (vector against itself scaled by 1.1)",
    "4.689064502037325e-21": "degenerate t-test (vector against itself scaled by 1.1)",
}


def load_results() -> dict:
    if not RESULTS.exists():
        sys.exit(f"missing {RESULTS.relative_to(ROOT)}")
    return json.loads(RESULTS.read_text(encoding="utf-8"))["results"]


def check_provenance(results: dict) -> list[str]:
    """A number without a traceable source is an assertion, not a result."""
    problems = []
    for key, r in results.items():
        if not r.get("source"):
            problems.append(f"{key}: no 'source' — cannot be traced to a computation")
        if not r.get("description"):
            problems.append(f"{key}: no 'description'")
        if "value" not in r:
            problems.append(f"{key}: no 'value'")
        has_n = any(k.startswith("n_") for k in r)
        if not has_n and r.get("unit") not in {"people", None}:
            problems.append(f"{key}: no sample count (n_subjects / n_rows)")
    return problems


def parse_number(text: str) -> float | None:
    """Pull a single number out of the claimed text, tolerating formatting."""
    cleaned = text.strip().replace(",", "").replace("−", "-").replace("**", "")
    m = re.search(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", cleaned)
    return float(m.group()) if m else None


def check_claims(results: dict) -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0

    for rel in DOCS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")

        # Mentions inside a retraction notice are the point, not a violation.
        asserted = RETRACTION_NOTICE.sub("", text)
        for bad, why in RETRACTED.items():
            if bad in asserted:
                problems.append(
                    f"{rel}: asserts retracted value {bad} — {why}. "
                    f"If documenting the retraction, wrap it in "
                    f"<!--!retracted-->...<!--/-->."
                )

        for match in CLAIM.finditer(text):
            key, shown = match.group(1), match.group(2)
            line = text[: match.start()].count("\n") + 1
            checked += 1

            if key not in results:
                problems.append(
                    f"{rel}:{line}: claims '{key}', which is not in results.json"
                )
                continue

            declared = float(results[key]["value"])
            found = parse_number(shown)
            if found is None:
                problems.append(f"{rel}:{line}: claim '{key}' has no number in {shown!r}")
                continue

            # Percent-valued results may be written either way (85.0 or 85%).
            candidates = {found}
            if results[key].get("unit") == "percent":
                candidates |= {found * 100, found / 100}

            if not any(abs(c - declared) < 1e-9 for c in candidates):
                problems.append(
                    f"{rel}:{line}: claim '{key}' says {found}, "
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
            print(f"{key:45s} {r['value']:>12} {n:10s} {r['source']}")
        return 0

    problems = check_provenance(results)
    claim_problems, checked = check_claims(results)
    problems += claim_problems

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

    print(f"OK — {checked} claims across {len(DOCS)} documents match results.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
