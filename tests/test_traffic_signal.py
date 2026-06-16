"""HSV traffic-signal colour detection (services/perception/traffic_signal.py).

Synthetic frames with a solid-colour patch inside the signal polygon must
classify to the matching state; an unlit / grey patch must report
"unknown" rather than guess.
"""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from services.perception.traffic_signal import (
    detect_signal_states,
    detect_signal_states_detailed,
    lamp_readings,
)

# ── Calibrated per-lamp path (position + brightness) ──

# A vertical signal head: three lamp points stacked. The lenses are ALWAYS
# their colour (coloured glass); only the lit lamp is bright. This is the
# case the whole-zone hue histogram cannot handle but calibration nails.
LAMPS = [
    {"color": "red", "point": [10, 10], "r": 4},
    {"color": "amber", "point": [10, 30], "r": 4},
    {"color": "green", "point": [10, 50], "r": 4},
]
_LAMP_BGR = {"red": (0, 0, 1.0), "amber": (0, 0.65, 1.0), "green": (0, 1.0, 0)}


def _lamp_frame(active, lit=255, off=55):
    """Frame where every lens shows its colour, but only ``active`` is bright."""
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    for lamp in LAMPS:
        c, (x, y) = lamp["color"], lamp["point"]
        v = lit if c == active else off
        col = tuple(int(round(ch * v)) for ch in _LAMP_BGR[c])
        cv2.rectangle(frame, (x - 4, y - 4), (x + 4, y + 4), col, -1)
    return frame


def _calibration():
    cal = {}
    for state in ("red", "amber", "green"):
        hsv = cv2.cvtColor(_lamp_frame(state), cv2.COLOR_BGR2HSV)
        r = lamp_readings(hsv, LAMPS)
        cal[state] = {c: r[c]["v"] for c in r}
    return cal


def _calibrated_zone():
    return [{"type": "signal", "name": "S",
             "points": [[5, 5], [55, 5], [55, 55], [5, 55]],
             "lamps": LAMPS, "calibration": _calibration()}]


def test_calibrated_picks_lit_lamp_despite_coloured_lenses():
    z = _calibrated_zone()
    assert detect_signal_states(_lamp_frame("red"), z) == {"S": "red"}
    assert detect_signal_states(_lamp_frame("amber"), z) == {"S": "amber"}
    assert detect_signal_states(_lamp_frame("green"), z) == {"S": "green"}


def test_calibrated_all_dark_is_unknown():
    # No lamp lit (e.g. between phases / flashing off): every lamp at its
    # off baseline, so nothing clears the lit margin.
    assert detect_signal_states(_lamp_frame("none"), _calibrated_zone()) == {"S": "unknown"}


def test_uncalibrated_brightest_lamp_heuristic():
    z = [{"type": "signal", "name": "S", "lamps": LAMPS}]  # lamps, no calibration
    assert detect_signal_states(_lamp_frame("green"), z) == {"S": "green"}
    assert detect_signal_states(_lamp_frame("none"), z) == {"S": "unknown"}


def test_detailed_keeps_lamp_readings_and_flag():
    detail = detect_signal_states_detailed(_lamp_frame("amber"), _calibrated_zone())["S"]
    assert detail["state"] == "amber"
    assert detail["calibrated"] is True
    assert set(detail["lamps"]) == {"red", "amber", "green"}
    assert detail["lamps"]["amber"]["v"] > detail["lamps"]["red"]["v"]

# A square zone covering the top-left 60x60 of a 200x200 frame.
ZONE = {"type": "signal", "name": "Signal", "points": [[10, 10], [70, 10], [70, 70], [10, 70]]}


def _frame_with_patch(bgr):
    """Black 200x200 BGR frame with the zone's region filled with ``bgr``."""
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.fillPoly(frame, [np.array(ZONE["points"], dtype=np.int32)], bgr)
    return frame


def test_detects_red():
    # BGR red.
    assert detect_signal_states(_frame_with_patch((0, 0, 255)), [ZONE]) == {"Signal": "red"}


def test_detects_green():
    assert detect_signal_states(_frame_with_patch((0, 255, 0)), [ZONE]) == {"Signal": "green"}


def test_detects_amber():
    # BGR orange/amber.
    assert detect_signal_states(_frame_with_patch((0, 165, 255)), [ZONE]) == {"Signal": "amber"}


def test_unlit_is_unknown():
    # Dark grey: low saturation/value, no lamp lit.
    assert detect_signal_states(_frame_with_patch((40, 40, 40)), [ZONE]) == {"Signal": "unknown"}


def test_no_signal_zone_returns_empty():
    zone = {"type": "zone", "name": "Area", "points": ZONE["points"]}
    assert detect_signal_states(_frame_with_patch((0, 0, 255)), [zone]) == {}


def test_no_zones_or_frame():
    assert detect_signal_states(None, [ZONE]) == {}
    assert detect_signal_states(_frame_with_patch((0, 0, 255)), None) == {}
    assert detect_signal_states(_frame_with_patch((0, 0, 255)), []) == {}


def test_detailed_exposes_scores():
    # The dashboard/calibration path keeps per-colour lit fractions.
    detail = detect_signal_states_detailed(_frame_with_patch((0, 0, 255)), [ZONE])
    assert detail["Signal"]["state"] == "red"
    scores = detail["Signal"]["scores"]
    assert scores["red"] > 0.5
    assert scores["green"] == 0.0
    assert set(scores) == {"red", "amber", "green"}


def test_multiple_signal_zones():
    far = {"type": "signal", "name": "Far",
           "points": [[120, 120], [180, 120], [180, 180], [120, 180]]}
    frame = _frame_with_patch((0, 0, 255))  # near zone red
    cv2.fillPoly(frame, [np.array(far["points"], dtype=np.int32)], (0, 255, 0))  # far green
    assert detect_signal_states(frame, [ZONE, far]) == {"Signal": "red", "Far": "green"}
