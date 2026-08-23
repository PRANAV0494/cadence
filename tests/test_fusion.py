"""
SPRT fusion tests: bounds from error rates, walk behaviour, no magic 0.4/0.6.
"""

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from fusion import ALPHA, BETA, DETECTOR_RATES, bounds, decide, signal_llr, update  # noqa: E402


# ── bounds derive from error rates, not hand-picked constants ──

def test_bounds_are_wald_derivations():
    lo, hi = bounds()
    expected_lo = math.log(BETA / (1 - ALPHA))
    expected_hi = math.log((1 - BETA) / ALPHA)
    assert math.isclose(lo, expected_lo)
    assert math.isclose(hi, expected_hi)


def test_bounds_asymmetry_favors_clearing_humans():
    """With alpha=0.05/beta=0.10, an attack needs MORE evidence to step up
    (ln 18 ~ 2.89) than a human needs to be cleared (|ln 0.105| ~ 2.25).
    The step-up call is the consequential one; the burden is on it."""
    lo, hi = bounds()
    assert abs(hi) > abs(lo)


def test_no_magic_thresholds():
    """The forbidden constants must appear nowhere in the bounds."""
    lo, hi = bounds()
    for value in (0.4, 0.6, -0.4, -0.6):
        assert not math.isclose(lo, value)
        assert not math.isclose(hi, value)


def test_tighter_alpha_widens_the_upper_bound():
    lo1, hi1 = bounds(alpha=0.05)
    lo2, hi2 = bounds(alpha=0.01)
    assert hi2 > hi1  # demanding fewer false step-ups needs more evidence


# ── per-signal contributions ───────────────────────────────────

def test_fired_signal_contributes_positive_llr():
    for name in DETECTOR_RATES:
        assert signal_llr(name, True) > 0


def test_silent_signal_contributes_negative_llr():
    for name in DETECTOR_RATES:
        llr = signal_llr(name, False)
        tpr, fpr = DETECTOR_RATES[name]
        if tpr < 1.0 and fpr < 1.0:
            assert llr < 0


def test_llr_matches_the_definition():
    tpr, fpr = DETECTOR_RATES["automation"]
    assert math.isclose(signal_llr("automation", True), math.log(tpr / fpr))


# ── the walk ───────────────────────────────────────────────────

def test_neutral_start_continues():
    r = update(0.0, {"automation": None, "drift": None, "provenance": None})
    assert r["decision"] == "continue"
    assert r["llr"] == 0.0


def test_single_automation_flag_is_terminal():
    """One automation flag carries ln(0.90/0.02) ~ 3.8 nats — past the 2.89
    bound on its own. Machine-perfect regularity is a near-certain attack
    signal at these measured rates; deferring would only risk the human
    case that a 2% fpr already prices in. If that ever proves too eager,
    the fix is recalibrating tpr/fpr from data, not a magic damping factor."""
    r = update(0.0, {"automation": True})
    assert r["decision"] == "step-up"


def test_single_drift_flag_alone_is_not_terminal():
    """Drift is the noisiest detector (tpr 0.70/fpr 0.05): one flag is
    ~2.6 nats, below the 2.89 bar — the walk continues."""
    r = update(0.0, {"drift": True})
    assert r["decision"] == "continue"
    assert 0 < r["llr"] < r["upper"]


def test_repeated_attack_evidence_steps_up():
    llr = 0.0
    decision = "continue"
    for _ in range(10):
        r = update(llr, {"automation": True, "drift": True, "provenance": True})
        llr, decision = r["llr"], r["decision"]
        if decision != "continue":
            break
    assert decision == "step-up"


def test_repeated_clean_evidence_declares_clean():
    llr = 0.0
    decision = "continue"
    for _ in range(20):
        r = update(llr, {"automation": False, "drift": False, "provenance": False})
        llr, decision = r["llr"], r["decision"]
        if decision != "continue":
            break
    assert decision == "clean"


def test_mixed_evidence_can_cancel():
    """An automation flag partially offset by clean provenance and drift."""
    r = update(0.0, {"automation": True, "drift": False, "provenance": False})
    assert r["llr"] > 0 and r["decision"] == "continue"


def test_unknown_detector_is_ignored():
    r = update(0.0, {"thermal_camera": True})
    assert r["llr"] == 0.0


def test_none_contributes_zero():
    r = update(1.5, {"automation": None})
    assert r["llr"] == 1.5


# ── decision function ──────────────────────────────────────────

def test_decide_at_and_past_bounds():
    lo, hi = bounds()
    assert decide(hi) == "step-up"
    assert decide(hi + 0.001) == "step-up"
    assert decide(lo) == "clean"
    assert decide(lo - 0.001) == "clean"
    assert decide(0.0) == "continue"
