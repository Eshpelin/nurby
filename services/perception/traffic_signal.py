"""Traffic-signal colour detection from a user-drawn zone.

A camera that watches an intersection can have one or more zones of
``type == "signal"`` drawn over a traffic-light head. For each such zone
we sample the pixels inside the polygon, convert to HSV, and decide which
of red / amber / green is lit (if any). The result is stamped onto the
rule-evaluation payload as ``signal_states: {zone_name: state}`` so the
``red_light_cross`` trigger can gate on a *detected* red instead of a
manually typed time window.

This is deliberately a classic-CV approach (hue histogram in an ROI), not
a model: it runs in well under a millisecond per zone, needs no weights,
and works fully offline. Accuracy depends on the user framing the zone
tightly on the lamp head; glare, sun behind the signal, and night blur
are the known failure modes, which is why ambiguous frames return
``"unknown"`` rather than guessing.
"""

from __future__ import annotations

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - cv2 always present in the worker
    cv2 = None  # type: ignore

# OpenCV HSV ranges: H is 0-179, S and V are 0-255. A pixel only counts
# toward a colour if it is saturated and bright enough to be a lit lamp,
# which rejects the dark housing, the grey pole, and the sky.
_MIN_SAT = 70
_MIN_VAL = 80
# A colour must claim at least this fraction of the zone's pixels to win,
# otherwise the lamp is off / between phases and we report "unknown".
_MIN_FRACTION = 0.02

SignalState = str  # "red" | "amber" | "green" | "unknown"


def _classify_hsv(hsv: np.ndarray, total: int) -> SignalState:
    """Pick the dominant lit colour in a flat (N, 3) HSV pixel array."""
    if total <= 0 or hsv.size == 0:
        return "unknown"
    h = hsv[:, 0]
    s = hsv[:, 1]
    v = hsv[:, 2]
    lit = (s >= _MIN_SAT) & (v >= _MIN_VAL)
    counts = {
        # Red wraps the hue circle, so it lives at both ends.
        "red": int(np.count_nonzero(lit & ((h <= 10) | (h >= 170)))),
        # Amber covers orange/yellow lamps.
        "amber": int(np.count_nonzero(lit & (h >= 11) & (h <= 33))),
        "green": int(np.count_nonzero(lit & (h >= 40) & (h <= 90))),
    }
    best = max(counts, key=counts.get)
    if counts[best] / total < _MIN_FRACTION:
        return "unknown"
    return best


def detect_signal_states(
    frame: np.ndarray | None, zones: list[dict] | None
) -> dict[str, SignalState]:
    """Map each ``type == "signal"`` zone name to its detected colour.

    ``frame`` must be the original (un-masked) BGR keyframe so motion-zone
    masking has not blacked out the lamp. Returns an empty dict when there
    are no signal zones, so callers pay nothing on non-traffic cameras.
    """
    if frame is None or cv2 is None or not zones:
        return {}
    signal_zones = [
        z for z in zones
        if z.get("type") == "signal" and len(z.get("points") or []) >= 3
    ]
    if not signal_zones:
        return {}

    h_img, w_img = frame.shape[:2]
    hsv_full: np.ndarray | None = None
    out: dict[str, SignalState] = {}
    for z in signal_zones:
        name = z.get("name") or "signal"
        mask = np.zeros((h_img, w_img), dtype=np.uint8)
        poly = np.array(z["points"], dtype=np.int32)
        cv2.fillPoly(mask, [poly], 255)
        sel = mask.astype(bool)
        total = int(np.count_nonzero(sel))
        if total <= 0:
            out[name] = "unknown"
            continue
        if hsv_full is None:
            hsv_full = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        out[name] = _classify_hsv(hsv_full[sel], total)
    return out
