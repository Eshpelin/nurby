"""HSV traffic-signal colour detection (services/perception/traffic_signal.py).

Synthetic frames with a solid-colour patch inside the signal polygon must
classify to the matching state; an unlit / grey patch must report
"unknown" rather than guess.
"""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from services.perception.traffic_signal import detect_signal_states

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


def test_multiple_signal_zones():
    far = {"type": "signal", "name": "Far",
           "points": [[120, 120], [180, 120], [180, 180], [120, 180]]}
    frame = _frame_with_patch((0, 0, 255))  # near zone red
    cv2.fillPoly(frame, [np.array(far["points"], dtype=np.int32)], (0, 255, 0))  # far green
    assert detect_signal_states(frame, [ZONE, far]) == {"Signal": "red", "Far": "green"}
