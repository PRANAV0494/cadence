"""
Tests for the documentation-consistency checker.

The checker's failure modes were originally verified by hand, which is exactly
the kind of assurance that decays. These lock them in.

The most important test here is `test_splitting_a_marker_to_smuggle_precision`:
the first version of the checker was defeated by writing
`<!--@key-->3.11<!--/-->27`, which renders as 3.1127 while verifying only 3.11.
That was caught in review, not by the checker.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))

from check_docs import (  # noqa: E402
    check_claims,
    check_provenance,
    load_docs,
)

ROOT = Path(__file__).resolve().parents[1]


def results(**overrides):
    base = {
        "t_stat": {
            "value": 3.1127,
            "n_subjects": 51,
            "source": "README.md",
            "description": "paired t-test",
        },
        "pct": {
            "value": 85.0,
            "unit": "percent",
            "n_rows": 293,
            "source": "README.md",
            "description": "share negative",
        },
    }
    base.update(overrides)
    return base


def problems_for(text, res=None):
    return check_claims(res or results(), {"doc.md": text})[0]


# ── agreement ──────────────────────────────────────────────────

def test_exact_match_passes():
    assert problems_for("t = <!--@t_stat-->3.1127<!--/-->") == []


def test_document_may_round_the_declared_value():
    """3.1127 shown as 3.11 is honest rounding, not drift."""
    assert problems_for("t = <!--@t_stat-->3.11<!--/-->") == []
    assert problems_for("t = <!--@t_stat-->3.113<!--/-->") == []
    assert problems_for("t = <!--@t_stat-->3<!--/-->") == []


def test_disagreement_fails():
    out = problems_for("t = <!--@t_stat-->3.9<!--/-->")
    assert len(out) == 1 and "shows 3.9" in out[0]


def test_rounding_must_be_correct_not_merely_shorter():
    """3.1127 rounds to 3.11, never 3.12."""
    assert problems_for("t = <!--@t_stat-->3.12<!--/-->") != []


def test_percent_units_accept_either_form():
    assert problems_for("<!--@pct-->85%<!--/-->") == []
    assert problems_for("<!--@pct-->0.85<!--/-->") == []


# ── the defect this checker shipped with ───────────────────────

def test_splitting_a_marker_to_smuggle_precision():
    """
    Renders as 3.1127; only 3.11 is inside the markers. This defeated the
    first version of the checker and was caught in review.
    """
    out = problems_for("t = <!--@t_stat-->3.11<!--/-->27")
    assert len(out) == 1
    assert "must be inside the markers" in out[0]


def test_trailing_decimal_point_also_caught():
    assert problems_for("t = <!--@t_stat-->3.11<!--/-->.5") != []


def test_ordinary_text_after_a_marker_is_fine():
    assert problems_for("t = <!--@t_stat-->3.11<!--/--> on 51 subjects") == []


# ── unknown keys and malformed markers ─────────────────────────

def test_unknown_key_fails():
    out = problems_for("<!--@no_such_key-->1.0<!--/-->")
    assert len(out) == 1 and "not in results.json" in out[0]


def test_unclosed_marker_does_not_pass_silently():
    out = problems_for("t = <!--@t_stat-->3.11")
    assert any("malformed claim marker" in p for p in out)


def test_claim_without_a_number_fails():
    out = problems_for("<!--@t_stat-->about three<!--/-->")
    assert any("no number" in p for p in out)


# ── retracted values ───────────────────────────────────────────

def test_asserting_a_retracted_value_fails():
    out = problems_for("Our method achieves p = 4.7e-21.")
    assert any("retracted" in p for p in out)


def test_documenting_a_retraction_is_allowed():
    text = "The bogus <!--!retracted-->p = 4.7e-21<!--/--> came from a bad cell."
    assert problems_for(text) == []


def test_unclosed_retraction_marker_is_caught():
    out = problems_for("<!--!retracted-->p = 4.7e-21")
    assert any("malformed retraction" in p for p in out)


# ── provenance ─────────────────────────────────────────────────

def test_missing_source_fails():
    r = results()
    del r["t_stat"]["source"]
    assert any("no 'source'" in p for p in check_provenance(r, ROOT))


def test_unresolvable_source_fails():
    r = results()
    r["t_stat"]["source"] = "nowhere/at/all.ipynb"
    assert any("does not exist" in p for p in check_provenance(r, ROOT))


def test_external_and_private_sources_are_exempt_from_path_resolution():
    r = results()
    r["t_stat"]["source"] = "external: Killourhy & Maxion, DSN 2009"
    r["pct"]["source"] = "private:data/private/export.csv"
    assert [p for p in check_provenance(r, ROOT) if "exist" in p] == []


def test_missing_sample_count_fails_even_without_a_unit():
    """
    A unitless entry used to skip the sample-count check entirely, because
    `r.get("unit")` returns None and None was in the exemption set.
    """
    r = results()
    del r["t_stat"]["n_subjects"]
    assert any("sample count" in p for p in check_provenance(r, ROOT))


def test_people_unit_is_exempt_from_sample_count():
    r = {
        "participants": {
            "value": 49,
            "unit": "people",
            "source": "README.md",
            "description": "consenting participants",
        }
    }
    assert [p for p in check_provenance(r, ROOT) if "sample count" in p] == []


# ── repository-wide scanning ───────────────────────────────────

def test_every_markdown_file_is_scanned():
    """
    A hardcoded file list is how the retracted p-value survived in docs/ while
    the checker looked at three other files.
    """
    scanned = load_docs(ROOT)
    on_disk = {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*.md")
        if not p.relative_to(ROOT).as_posix().startswith(
            (".git/", "node_modules/", "reference/", "tests/legacy/")
        )
    }
    assert on_disk <= set(scanned), f"unscanned: {on_disk - set(scanned)}"
    assert "docs/CADENCE_PLAN.md" in scanned
