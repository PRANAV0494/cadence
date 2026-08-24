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


def test_drift_flag_terminality_follows_the_measured_rates():
    """With placeholder rates (tpr 0.70/fpr 0.05) one drift flag was 2.6
    nats — below the bar. The measured fixture rates are near-perfect
    (smoothed tpr 0.97/fpr 0.0098), so one flag is ln(99) ~ 4.6 nats and
    IS terminal. That is the honest consequence of an easy fixture: the
    rates carry the fixture's confidence, and recalibrating on harder
    data will walk this back. What must hold either way: the LLR is
    finite and the decision follows the bound."""
    r = update(0.0, {"drift": True})
    assert r["llr"] > 0
    tpr, fpr = DETECTOR_RATES["drift"]
    import math as _m
    expected = _m.log(tpr / fpr)
    assert abs(r["llr"] - expected) < 1e-9
    assert r["decision"] == ("step-up" if expected >= r["upper"] else "continue")


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
    """An automation flag offset by clean provenance and drift can land
    anywhere relative to the bounds - what must hold is the arithmetic:
    the sum of the individual LLRs, nothing more, nothing less."""
    import math as _m

    r = update(0.0, {"automation": True, "drift": False, "provenance": False})
    expected = sum(
        _m.log((1 - DETECTOR_RATES[n][0]) / (1 - DETECTOR_RATES[n][1]))
        if not fired else _m.log(DETECTOR_RATES[n][0] / DETECTOR_RATES[n][1])
        for n, fired in (("automation", True), ("drift", False), ("provenance", False))
    )
    assert abs(r["llr"] - expected) < 1e-9


def test_unknown_detector_is_ignored():
    r = update(0.0, {"thermal_camera": True})
    assert r["llr"] == 0.0


def test_none_contributes_zero():
    r = update(1.5, {"automation": None})
    assert r["llr"] == 1.5


# ── decision function ──────────────────────────────────────────

def test_rates_come_from_results_json():
    """[PR 21] The automation/drift rates are loaded from
    evaluation/results.json, measured by calibrate_detectors.py - not
    hardcoded opinions. Values must match the file exactly."""
    import json

    import fusion

    data = json.loads(
        (Path(fusion.__file__).resolve().parents[1] / "evaluation" / "results.json")
        .read_text(encoding="utf-8")
    )["results"]
    def _smooth(entry):
        return (entry["value"] * entry["n_streams"] + 0.5) / (entry["n_streams"] + 1.0)

    assert fusion.DETECTOR_RATES["automation"] == (
        _smooth(data["detector_automation_tpr"]),
        _smooth(data["detector_automation_fpr"]),
    )
    assert fusion.DETECTOR_RATES["drift"] == (
        _smooth(data["detector_drift_tpr"]),
        _smooth(data["detector_drift_fpr"]),
    )


def test_measured_rates_have_provenance():
    """Every measured rate entry carries n and a repo source."""
    import json

    import fusion

    data = json.loads(
        (Path(fusion.__file__).resolve().parents[1] / "evaluation" / "results.json")
        .read_text(encoding="utf-8")
    )["results"]
    for key in ("detector_automation_tpr", "detector_automation_fpr",
                "detector_drift_tpr", "detector_drift_fpr"):
        entry = data[key]
        assert entry.get("n_streams", 0) > 0, key
        assert "calibrate_detectors.py" in entry["source"], key


def test_results_json_matches_the_calibration_script():
    """results.json's detector entries are exactly what measure() produced -
    pins the file to the script so a stale file cannot survive quietly."""
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation"))
    from calibrate_detectors import measure, results_entries

    data = json.loads(
        (Path(__file__).resolve().parents[1] / "evaluation" / "results.json")
        .read_text(encoding="utf-8")
    )["results"]
    entries = results_entries(measure())
    for key, entry in entries.items():
        assert data[key]["value"] == entry["value"], key


def test_decide_at_and_past_bounds():
    lo, hi = bounds()
    assert decide(hi) == "step-up"
    assert decide(hi + 0.001) == "step-up"
    assert decide(lo) == "clean"
    assert decide(lo - 0.001) == "clean"
    assert decide(0.0) == "continue"
