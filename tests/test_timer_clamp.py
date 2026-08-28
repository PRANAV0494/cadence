"""Timer-clamp quantization only — no invented EER."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evaluation.timer_clamp import (  # noqa: E402
    RESOLUTIONS_MS,
    quantize,
    quantize_events,
)


def test_quantize_floors_onto_the_grid():
    assert quantize(12.9, 2.0) == 12.0
    assert quantize(100.0, 100.0) == 100.0


def test_quantize_events_copies():
    src = [{"timestamp": 5.5, "key": "a"}]
    out = quantize_events(src, 2.0)
    assert out[0]["timestamp"] == 4.0
    assert src[0]["timestamp"] == 5.5


def test_module_invents_no_eer():
    """The module's stated contract: it quantizes, it does not report an
    EER. A later eer() helper must fail here, not ship quietly."""
    import evaluation.timer_clamp as tc

    assert not [name for name in dir(tc) if "eer" in name.lower()]


def test_production_scoring_is_isolated():
    """Nothing on the live scoring path imports the quantizer: replay
    numbers with clamped clocks are an offline experiment, not what the
    proxy enforces."""
    for prod in (
        REPO / "cadence" / "eval.py",
        REPO / "edge" / "fusion.py",
        REPO / "edge" / "addon.py",
    ):
        assert "timer_clamp" not in prod.read_text(encoding="utf-8")


def test_resolution_grids_roundtrip_through_replay():
    """The published grids are actually exercised: a jittery stream
    snapped to the Firefox grid lands on 2 ms multiples and still
    replays end to end."""
    from cadence.eval import replay
    from evaluation.harness.streams import human_jitter

    step = RESOLUTIONS_MS["firefox"]
    rounds = [quantize_events(r, step) for r in human_jitter(40)]
    assert all(e["timestamp"] % step == 0 for r in rounds for e in r)
    assert replay(rounds)["decision"] in ("clean", "continue", "step-up")
