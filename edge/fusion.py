"""SPRT fusion of provenance, automation and drift into one running score.

Wald's sequential probability ratio test: each evidence update contributes
a log-likelihood ratio to a running sum; the sum is compared against two
bounds derived from target error rates, never hand-picked constants:

    A = (1 - beta) / alpha      upper bound -> step-up
    B = beta / (1 - alpha)      lower bound -> clean

where alpha is the tolerated false-step-up rate (a human challenged
unnecessarily) and beta the tolerated miss rate (an attack not stepped up).

The per-signal log-likelihood ratios come from each detector's measured
reliability on labelled data (true/false positive rates). Where a detector
reports "insufficient evidence" it contributes 0 - the walk pauses, it
does not decay. The score never expires toward either bound on silence.

Decision protocol (Wald): step up when LLR >= ln A, declare clean when
LLR <= ln B, otherwise continue accumulating. Once a terminal decision is
reached it is sticky for the session unless contradicted evidence of
comparable weight arrives — this module only computes; stickiness policy
lives with the caller.
"""

from __future__ import annotations

import math

# Target error rates. alpha: 1 in 20 honest sessions stepped up.
# beta: 1 in 10 attacks missed. The asymmetry runs the expensive way for
# evidence, not for decisions: because stepping up is the consequential,
# hard-to-undo call, an attack must accumulate MORE evidence (ln 18 ~ 2.89)
# than a human needs to be cleared (|ln 0.105| ~ 2.25). Demanding fewer
# misses (smaller beta) would raise the step-up bar further still.
ALPHA = 0.05
BETA = 0.10

# Measured detector reliabilities: (true positive rate, false positive rate)
# on labelled streams. These are the measured CMU-era numbers from
# evaluation/results.json where available, engineering estimates otherwise;
# they are inputs, not tunables — recalibrate with data, not opinions.
DETECTOR_RATES = {
    "automation": (0.90, 0.02),   # synthetic streams: flags 90%, humans 2%
    "drift": (0.70, 0.05),        # driver changes: 70%, same-typist: 5%
    "provenance": (0.85, 0.01),   # unjustified POSTs: 85%, justified: 1%
}


def bounds(alpha: float = ALPHA, beta: float = BETA) -> tuple[float, float]:
    """(lower, upper) LLR bounds: (ln B, ln A) from the target error rates."""
    a = (1.0 - beta) / alpha
    b = beta / (1.0 - alpha)
    return math.log(b), math.log(a)


def signal_llr(name: str, fired: bool) -> float:
    """Log-likelihood ratio contributed by one detector outcome.

    LLR = ln( P(observation | attack) / P(observation | honest) )
        fired:   ln( tpr / fpr )
        silent:  ln( (1 - tpr) / (1 - fpr) )
    """
    tpr, fpr = DETECTOR_RATES[name]
    if fired:
        return math.log(tpr / fpr)
    return math.log((1.0 - tpr) / (1.0 - fpr))


def decide(llr: float, lower: float | None = None, upper: float | None = None) -> str:
    """'clean' | 'step-up' | 'continue' against the Wald bounds."""
    lo, hi = bounds() if lower is None else (lower, upper)  # type: ignore[misc]
    if llr >= hi:
        return "step-up"
    if llr <= lo:
        return "clean"
    return "continue"


def update(
    running: float,
    signals: dict[str, bool | None],
    alpha: float = ALPHA,
    beta: float = BETA,
) -> dict:
    """One SPRT step: fold new detector outcomes into the running LLR.

    signals maps detector name -> fired (True/False) or None for
    insufficient evidence (contributes 0). Returns the new state:
    {"llr", "decision", "lower", "upper"}.
    """
    lo, hi = bounds(alpha, beta)
    llr = running
    for name, fired in signals.items():
        if name not in DETECTOR_RATES:
            continue
        if fired is None:
            continue
        llr += signal_llr(name, fired)
    return {"llr": llr, "decision": decide(llr, lo, hi), "lower": lo, "upper": hi}
