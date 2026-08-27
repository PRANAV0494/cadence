"""Timer-clamp quantization only — no invented EER."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evaluation.timer_clamp import quantize, quantize_events  # noqa: E402


def test_quantize_floors_onto_the_grid():
    assert quantize(12.9, 2.0) == 12.0
    assert quantize(100.0, 100.0) == 100.0


def test_quantize_events_copies():
    src = [{"timestamp": 5.5, "key": "a"}]
    out = quantize_events(src, 2.0)
    assert out[0]["timestamp"] == 4.0
    assert src[0]["timestamp"] == 5.5
