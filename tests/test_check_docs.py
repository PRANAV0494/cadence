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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))

from check_docs import (  # noqa: E402
    DOC_EXCLUDE_PARTS,
    DOC_EXCLUDE_PREFIXES,
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


def test_percent_form_must_match_the_displayed_form():
    """
    Accepting both 85 and 0.85 unconditionally let a claim be wrong by 100x.
    '0.85%' displays a hundredth of the declared 85%.
    """
    assert problems_for("<!--@pct-->0.85%<!--/-->") != []
    assert problems_for("<!--@pct-->85<!--/-->") != []


def test_scientific_notation_compares_without_rounding():
    """
    round(1.23e-05, 0) is 0.0, so rounding-aware comparison rejected every
    scientific claim, including exact matches. This repo traffics in p-values.
    """
    r = {"tiny_p": {"value": 1.23e-05, "n_rows": 10,
                    "source": "README.md", "description": "p"}}
    assert problems_for("p = <!--@tiny_p-->1.23e-05<!--/-->", r) == []
    assert problems_for("p = <!--@tiny_p-->9.9e-03<!--/-->", r) != []


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


def test_leading_digit_smuggles_from_the_other_side():
    """9<!--@k-->0.1367<!--/--> renders 90.1367. The first fix only guarded
    the trailing side; this is the same defect mirrored."""
    out = problems_for("9<!--@t_stat-->3.1127<!--/-->")
    assert len(out) == 1 and "preceded by" in out[0]


def test_leading_minus_flips_a_verified_sign():
    out = problems_for("-<!--@t_stat-->3.1127<!--/-->")
    assert any("preceded by" in p for p in out)


def test_leading_digit_dot_is_caught():
    out = problems_for("1.<!--@t_stat-->3.1127<!--/-->")
    assert any("preceded by" in p for p in out)


def test_trailing_exponent_is_caught():
    """3.11<!--/-->e-21 renders 3.11e-21; a digits-only guard misses 'e'."""
    out = problems_for("t = <!--@t_stat-->3.1127<!--/-->e-21")
    assert any("followed by" in p for p in out)


def test_trailing_percent_is_caught():
    out = problems_for("<!--@pct-->85<!--/-->%")
    assert any("followed by" in p for p in out)


def test_sentence_punctuation_is_not_smuggling():
    """A lone '.' ends a sentence; only '.' followed by a digit extends a number."""
    assert problems_for("The EER is <!--@t_stat-->3.1127<!--/-->. Next sentence.") == []
    assert problems_for("<!--@t_stat-->3.1127<!--/-->, which is high") == []
    assert problems_for("(<!--@t_stat-->3.1127<!--/-->)") == []


def test_soft_wrapped_line_ending_in_a_digit_is_not_smuggling():
    """
    A dollar anchor matches before a trailing newline as well as at the end of
    the string, so a line wrapping right after a digit tripped the leading
    guard. Markdown renders that soft break as a space, so nothing is smuggled.
    The pattern is anchored to the true end of the string now.
    """
    doc = "across all 51\n<!--@t_stat-->3.1127<!--/--> subjects"
    assert problems_for(doc) == []


def test_percent_form_mismatch_explains_itself():
    """
    A form mismatch used to report two identical numbers -- 'shows 85.0,
    results.json says 85.0' -- which reads as nonsense.
    """
    out = problems_for("<!--@pct-->85<!--/-->")
    assert len(out) == 1
    assert "percent result shown as bare" in out[0]
    assert "85%" in out[0] and "0.85" in out[0]


def test_scientific_claims_may_be_displayed_rounded():
    """
    Decimals may be shown rounded; e-notation must honour the same contract,
    since tiny p-values are exactly where it gets used.
    """
    r = {"tiny": {"value": 1.2345e-05, "n_rows": 10,
                  "source": "README.md", "description": "p"}}
    assert problems_for("p = <!--@tiny-->1.23e-05<!--/-->", r) == []
    assert problems_for("p = <!--@tiny-->1.2345e-05<!--/-->", r) == []
    assert problems_for("p = <!--@tiny-->9.9e-03<!--/-->", r) != []


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
    assert any("not a plain number" in p or "no number" in p for p in out)


def test_comment_inside_a_marker_body_is_rejected():
    """
    Renders 3.1127 while only 3.11 is compared — the smuggling defect moved
    inside the span, where the round-2 guards could not see it.
    """
    for body in ("3.11<!--x-->27", "3.11<!---->27"):
        out = problems_for(f"<!--@t_stat-->{body}<!--/-->")
        assert any("not a plain number" in p for p in out), body


def test_html_entity_inside_a_marker_body_is_rejected():
    """&#50; renders as '2', so 3.11&#50;7 displays 3.1127."""
    out = problems_for("<!--@t_stat-->3.11&#50;7<!--/-->")
    assert any("not a plain number" in p for p in out)


def test_partially_wrapped_retraction_is_caught():
    """
    Comment markers are invisible but the text between them renders, so
    `4.7e-2<!--!retracted-->1<!--/-->` displays the live value. Deleting whole
    spans hid this: the literal never formed in the stripped text.
    """
    for doc in ("Our p = 4.7e-2<!--!retracted-->1<!--/--> here",
                "Our p = 4.7e<!--!retracted-->-21<!--/--> here"):
        out = problems_for(doc)
        assert any("retracted" in p for p in out), doc


def test_fully_wrapped_retraction_still_allowed():
    assert problems_for("see <!--!retracted-->p = 4.7e-21<!--/--> above") == []


def test_non_numeric_declared_value_is_reported_not_raised():
    """value: null used to surface as TypeError from float()."""
    r = {"k": {"value": None, "n_rows": 1, "source": "README.md", "description": "d"}}
    out = problems_for("<!--@k-->1.0<!--/-->", r)
    assert any("non-numeric value" in p for p in out)


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

def test_nested_reference_dirs_are_excluded_too():
    """Only top-level reference/ was excluded; edge/reference/ was not."""
    assert "reference" in DOC_EXCLUDE_PARTS
    scanned = load_docs(ROOT)
    assert not any("reference" in Path(rel).parts for rel in scanned)


def test_every_markdown_file_is_scanned():
    """
    A hardcoded file list is how the retracted p-value survived in docs/ while
    the checker looked at three other files.
    """
    scanned = load_docs(ROOT)
    def excluded(rel: str) -> bool:
        return bool(set(Path(rel).parts) & DOC_EXCLUDE_PARTS) or rel.startswith(
            DOC_EXCLUDE_PREFIXES
        )

    on_disk = {
        rel
        for rel in (p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.md"))
        if not excluded(rel)
    }
    assert on_disk <= set(scanned), f"unscanned: {on_disk - set(scanned)}"
    assert "docs/CADENCE_PLAN.md" in scanned


# ── provenance holes the review kept flagging ──────────────────

def test_zero_or_null_sample_count_is_rejected():
    """n_subjects: 0 satisfied a presence check while saying nothing."""
    for bad in (0, None, -3, True):
        r = {"k": {"value": 1.0, "n_subjects": bad,
                   "source": "README.md", "description": "d"}}
        out = check_provenance(r, ROOT)
        assert any("positive integer" in p for p in out), bad


def test_empty_external_prefix_is_rejected():
    """'external:' with nothing after it opts out of the check rather than
    providing provenance."""
    r = {"k": {"value": 1.0, "n_rows": 5, "source": "external:   ",
               "description": "d"}}
    assert any("no detail after the prefix" in p for p in check_provenance(r, ROOT))


def test_derived_source_must_name_real_results():
    base = {"value": 1.0, "n_rows": 5, "description": "d"}
    good = {
        "a": {**base, "source": "README.md"},
        "b": {**base, "source": "derived: a"},
    }
    assert [p for p in check_provenance(good, ROOT) if "derived" in p] == []

    bad = {"b": {**base, "source": "derived: no_such_key"}}
    assert any("not a result" in p for p in check_provenance(bad, ROOT))

    empty = {"b": {**base, "source": "derived:"}}
    assert any("names no source results" in p for p in check_provenance(empty, ROOT))
