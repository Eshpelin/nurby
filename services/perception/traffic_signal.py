"""Traffic-signal colour detection from a user-drawn zone.

A camera that watches an intersection can have one or more zones of
``type == "signal"`` drawn over a traffic-light head. There are two ways the
state is read, in order of preference:

1. **Calibrated, per-lamp (robust).** The user marks the three lamp
   positions (``lamps``: red/amber/green points) and runs a short
   calibration: with the light actually red, capture; repeat for amber and
   green. We record each lamp's brightness in each state. At runtime we
   measure each lamp's brightness and pick the one that is most "lit"
   relative to its own dark baseline. This is the right model because the
   lamp *lenses are always coloured glass* - a red lens reads red even when
   off - so the discriminator is not "is there red" but "which lamp is
   brighter than when it is off". Position tells us which lamp is which.

2. **Uncalibrated heuristic.** Lamps marked but not calibrated yet: the
   brightest lamp by a clear margin wins, else ``unknown``.

3. **Legacy whole-zone hue.** No lamps marked: sample the whole polygon and
   pick the dominant lit hue. Fragile against always-coloured lenses, kept
   only as a zero-config fallback.

All paths are classic CV (brightness / hue in an ROI), no model, fully
offline. ``detect_signal_states`` returns ``{zone: state}`` for the rule
engine; ``detect_signal_states_detailed`` keeps per-lamp readings and scores
for the live dashboard readout and the calibration UI.
"""

from __future__ import annotations

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - cv2 always present in the worker
    cv2 = None  # type: ignore

# Legacy whole-zone hue path. OpenCV HSV: H 0-179, S/V 0-255.
_MIN_SAT = 70
_MIN_VAL = 80
_MIN_FRACTION = 0.02

# Per-lamp path.
_LAMP_RADIUS = 6          # half-size of the pixel patch sampled per lamp
_LIT_MARGIN = 0.5         # normalized lit-ness needed to call a calibrated lamp on
_RAW_LIT_MIN = 90         # min raw brightness for the uncalibrated heuristic
_RAW_LIT_MARGIN = 40      # how much the brightest lamp must beat the others (uncalibrated)

_COLORS = ("red", "amber", "green")
SignalState = str  # "red" | "amber" | "green" | "unknown"


# ── Legacy whole-zone hue classifier ──────────────────────────────

def _classify_hsv(hsv: np.ndarray, total: int) -> tuple[SignalState, dict[str, float]]:
    """Dominant lit colour in a flat (N, 3) HSV array, with per-colour scores."""
    zero = {"red": 0.0, "amber": 0.0, "green": 0.0}
    if total <= 0 or hsv.size == 0:
        return "unknown", zero
    h = hsv[:, 0]
    s = hsv[:, 1]
    v = hsv[:, 2]
    lit = (s >= _MIN_SAT) & (v >= _MIN_VAL)
    counts = {
        "red": int(np.count_nonzero(lit & ((h <= 10) | (h >= 170)))),
        "amber": int(np.count_nonzero(lit & (h >= 11) & (h <= 33))),
        "green": int(np.count_nonzero(lit & (h >= 40) & (h <= 90))),
    }
    scores = {k: round(c / total, 4) for k, c in counts.items()}
    best = max(counts, key=counts.get)
    state = best if counts[best] / total >= _MIN_FRACTION else "unknown"
    return state, scores


# ── Per-lamp sampling + calibrated classifier ──────────────────────

def _sample_point(hsv: np.ndarray, x: float, y: float, rad: int) -> dict | None:
    """Mean HSV of a small patch around (x, y), or None if off-frame."""
    h_img, w_img = hsv.shape[:2]
    x0, x1 = max(0, int(x - rad)), min(w_img, int(x + rad) + 1)
    y0, y1 = max(0, int(y - rad)), min(h_img, int(y + rad) + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = hsv[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    return {
        "h": round(float(patch[:, 0].mean()), 1),
        "s": round(float(patch[:, 1].mean()), 1),
        "v": round(float(patch[:, 2].mean()), 1),
    }


def lamp_readings(hsv: np.ndarray, lamps: list[dict]) -> dict[str, dict]:
    """Sample each configured lamp. ``lamps`` is a list of
    ``{"color": "red"|"amber"|"green", "point": [x, y], "r"?: int}``.
    Returns ``{color: {"h","s","v"}}`` for every lamp that lands on-frame."""
    out: dict[str, dict] = {}
    for lamp in lamps or []:
        color = lamp.get("color")
        pt = lamp.get("point")
        if color not in _COLORS or not (isinstance(pt, (list, tuple)) and len(pt) == 2):
            continue
        rad = int(lamp.get("r") or _LAMP_RADIUS)
        reading = _sample_point(hsv, pt[0], pt[1], rad)
        if reading is not None:
            out[color] = reading
    return out


def _has_calibration(calibration: dict | None) -> bool:
    """True when every state has been captured with a usable per-lamp map."""
    if not isinstance(calibration, dict):
        return False
    return all(isinstance(calibration.get(s), dict) and calibration[s] for s in _COLORS)


def classify_calibrated(
    readings: dict[str, dict], calibration: dict
) -> tuple[SignalState, dict[str, float]]:
    """Pick the lit lamp by comparing each lamp's current brightness to its
    own calibrated off-baseline. ``calibration[state][lamp]`` is that lamp's
    brightness (V) when ``state`` was active. Scores are normalized lit-ness
    in [0, ~1]; the brightest wins if it clears ``_LIT_MARGIN``."""
    scores: dict[str, float] = {}
    for lamp in _COLORS:
        if lamp not in readings:
            continue
        on = (calibration.get(lamp) or {}).get(lamp)
        offs = [
            (calibration.get(s) or {}).get(lamp)
            for s in _COLORS if s != lamp
        ]
        offs = [o for o in offs if isinstance(o, (int, float))]
        if not isinstance(on, (int, float)) or not offs:
            continue
        off = sum(offs) / len(offs)
        denom = on - off
        v = readings[lamp]["v"]
        scores[lamp] = round((v - off) / denom, 3) if denom > 1e-6 else 0.0
    if not scores:
        return "unknown", {}
    best = max(scores, key=scores.get)
    state = best if scores[best] >= _LIT_MARGIN else "unknown"
    return state, scores


def _classify_brightest(readings: dict[str, dict]) -> tuple[SignalState, dict[str, float]]:
    """Uncalibrated fallback: brightest lamp wins if it clearly beats the
    others. Scores are raw brightness normalized to [0, 1]."""
    vs = {c: readings[c]["v"] for c in readings}
    if not vs:
        return "unknown", {}
    scores = {c: round(v / 255.0, 3) for c, v in vs.items()}
    best = max(vs, key=vs.get)
    others = [v for c, v in vs.items() if c != best]
    margin = vs[best] - (sum(others) / len(others) if others else 0.0)
    state = best if vs[best] >= _RAW_LIT_MIN and margin >= _RAW_LIT_MARGIN else "unknown"
    return state, scores


# ── Public API ─────────────────────────────────────────────────────

def _sample(frame: np.ndarray | None, zones: list[dict] | None) -> dict[str, dict]:
    """Per-signal-zone ``{"state","scores",["lamps","calibrated"]}``.
    ``frame`` must be the original (un-masked) BGR keyframe. Empty dict when
    there are no signal zones, so non-traffic cameras pay nothing."""
    if frame is None or cv2 is None or not zones:
        return {}
    signal_zones = [z for z in zones if z.get("type") == "signal"]
    if not signal_zones:
        return {}

    hsv_full: np.ndarray | None = None
    out: dict[str, dict] = {}
    for z in signal_zones:
        name = z.get("name") or "signal"
        lamps = z.get("lamps") or []
        if hsv_full is None:
            hsv_full = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        if lamps:
            readings = lamp_readings(hsv_full, lamps)
            calibration = z.get("calibration")
            if _has_calibration(calibration):
                state, scores = classify_calibrated(readings, calibration)
                calibrated = True
            else:
                state, scores = _classify_brightest(readings)
                calibrated = False
            out[name] = {
                "state": state,
                "scores": scores,
                "lamps": readings,
                "calibrated": calibrated,
            }
            continue

        # Legacy whole-zone hue path (no lamps marked).
        pts = z.get("points")
        if not (pts and len(pts) >= 3):
            out[name] = {"state": "unknown", "scores": {"red": 0.0, "amber": 0.0, "green": 0.0}}
            continue
        h_img, w_img = frame.shape[:2]
        mask = np.zeros((h_img, w_img), dtype=np.uint8)
        cv2.fillPoly(mask, [np.array(pts, dtype=np.int32)], 255)
        sel = mask.astype(bool)
        total = int(np.count_nonzero(sel))
        if total <= 0:
            out[name] = {"state": "unknown", "scores": {"red": 0.0, "amber": 0.0, "green": 0.0}}
            continue
        state, scores = _classify_hsv(hsv_full[sel], total)
        out[name] = {"state": state, "scores": scores}
    return out


def detect_signal_states(
    frame: np.ndarray | None, zones: list[dict] | None
) -> dict[str, SignalState]:
    """Map each signal zone name to its detected colour. Consumed by the rule
    engine via ``rule_data["signal_states"]``."""
    return {name: d["state"] for name, d in _sample(frame, zones).items()}


def detect_signal_states_detailed(
    frame: np.ndarray | None, zones: list[dict] | None
) -> dict[str, dict]:
    """Like ``detect_signal_states`` but keeps per-lamp readings and scores,
    for the live dashboard readout and the calibration UI."""
    return _sample(frame, zones)
