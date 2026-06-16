"""End-to-end signal detection on realistic pixels.

Two layers:

1. A *rendered* traffic signal that always runs in CI: a dark housing with
   three always-coloured lenses, a lit lamp with a bright core + glow bloom,
   sensor noise, and lens blur. This exercises the full
   ``lamp_readings -> calibrate -> classify`` pipeline against the exact
   failure mode flat synthetic patches miss (every lens is coloured, so only
   brightness distinguishes the lit lamp).

2. A *real-photo* hook that auto-discovers fixtures under
   ``tests/fixtures/signals/<name>/`` (see that folder's README) and
   validates the pipeline against actual photos. Skips when none are present,
   so it is optional but runs in CI the moment a fixture is added.
"""

import glob
import json
import os

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from services.perception.traffic_signal import detect_signal_states, lamp_readings

# ── 1. Rendered realistic signal ───────────────────────────────────

W, H = 64, 160
LENS_CENTRES = {"red": (32, 34), "amber": (32, 80), "green": (32, 126)}
LENS_R = 15
# BGR lens glass colours (the lens reads this even when the lamp is off).
LENS_BGR = {"red": (36, 36, 205), "amber": (28, 150, 215), "green": (55, 200, 60)}
LAMPS = [{"color": c, "point": list(LENS_CENTRES[c]), "r": 7} for c in ("red", "amber", "green")]
BOX = [[10, 6], [W - 10, 6], [W - 10, H - 6], [10, H - 6]]


def _render(state: str, seed: int) -> np.ndarray:
    """Render a vertical 3-lamp signal with ``state`` lit (or 'none')."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 16, np.uint8)
    cv2.rectangle(img, (10, 6), (W - 10, H - 6), (38, 38, 40), -1)  # housing
    glow = np.zeros((H, W, 3), np.float32)
    for color, ctr in LENS_CENTRES.items():
        lens = np.array(LENS_BGR[color], np.float32)
        lit = color == state
        body = np.clip(lens * (1.0 if lit else 0.28), 0, 255)  # off lens stays coloured but dim
        cv2.circle(img, ctr, LENS_R, body.astype(int).tolist(), -1)
        if lit:
            core = np.clip(lens * 1.2 + 110, 0, 255)  # bright hot core
            cv2.circle(img, ctr, LENS_R - 5, core.astype(int).tolist(), -1)
            cv2.circle(glow, ctr, LENS_R + 8, core.tolist(), -1)  # bloom seed
    glow = cv2.GaussianBlur(glow, (0, 0), 9)  # halation that bleeds onto housing + neighbours
    out = np.clip(img.astype(np.float32) + glow * 0.5, 0, 255)
    out = np.clip(out + rng.normal(0, 5, out.shape), 0, 255).astype(np.uint8)  # sensor noise
    return cv2.GaussianBlur(out, (3, 3), 0)  # optics blur


def _calibration(seed: int = 1) -> dict:
    cal = {}
    for state in ("red", "amber", "green"):
        hsv = cv2.cvtColor(_render(state, seed), cv2.COLOR_BGR2HSV)
        r = lamp_readings(hsv, LAMPS)
        cal[state] = {c: r[c]["v"] for c in r}
    return cal


def _zone(cal: dict | None = None) -> dict:
    return {"type": "signal", "name": "S", "points": BOX, "lamps": LAMPS,
            "calibration": cal if cal is not None else _calibration()}


def test_rendered_each_state_classifies():
    zone = _zone()
    for state in ("red", "amber", "green"):
        assert detect_signal_states(_render(state, seed=1), [zone]) == {"S": state}


def test_rendered_robust_to_fresh_noise():
    # Calibrate on one noise seed, classify frames rendered with a different
    # seed: detection must generalise, not memorise pixels.
    zone = _zone(_calibration(seed=1))
    for state in ("red", "amber", "green"):
        assert detect_signal_states(_render(state, seed=7), [zone]) == {"S": state}


def test_rendered_all_dark_is_unknown():
    assert detect_signal_states(_render("none", seed=3), [_zone()]) == {"S": "unknown"}


def test_rendered_image_is_genuinely_ambiguous_by_colour():
    # Proves the test is non-trivial: in a red-lit frame the green lens is
    # still clearly green (high saturation) just dimmer, so a colour-only
    # detector would see all three. Brightness is the real discriminator.
    hsv = cv2.cvtColor(_render("red", seed=1), cv2.COLOR_BGR2HSV)
    r = lamp_readings(hsv, LAMPS)
    assert r["green"]["s"] > 80          # green lens still saturated/coloured
    assert r["green"]["v"] < r["red"]["v"]  # but dimmer than the lit red lamp


# ── 2. Real-photo fixtures (optional, auto-discovered) ─────────────

_FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "signals")


def _signal_fixture_dirs():
    if not os.path.isdir(_FIXTURE_ROOT):
        return []
    return sorted(
        d for d in glob.glob(os.path.join(_FIXTURE_ROOT, "*"))
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "lamps.json"))
    )


def _find_image(d: str, stem: str):
    for ext in ("jpg", "jpeg", "png"):
        p = os.path.join(d, f"{stem}.{ext}")
        if os.path.exists(p):
            return p
    return None


@pytest.mark.parametrize("signal_dir", _signal_fixture_dirs())
def test_real_signal_photo(signal_dir):
    with open(os.path.join(signal_dir, "lamps.json")) as fh:
        lamps = json.load(fh)["lamps"]

    cal, imgs = {}, {}
    for state in ("red", "amber", "green"):
        path = _find_image(signal_dir, state)
        if path is None:
            pytest.skip(f"{signal_dir}: missing {state} calibration image")
        img = cv2.imread(path)
        assert img is not None, f"could not read {path}"
        imgs[state] = img
        r = lamp_readings(cv2.cvtColor(img, cv2.COLOR_BGR2HSV), lamps)
        cal[state] = {c: r[c]["v"] for c in r}

    zone = {"type": "signal", "name": "S", "lamps": lamps, "calibration": cal}

    # Closed loop: each calibration image classifies back to its own state.
    for state, img in imgs.items():
        assert detect_signal_states(img, [zone])["S"] == state, f"{signal_dir}: {state} misread"

    # Held-out shots named "<state>_test*.{jpg,png}" must classify correctly.
    for path in sorted(glob.glob(os.path.join(signal_dir, "*_test*"))):
        expect = os.path.basename(path).split("_test")[0]
        img = cv2.imread(path)
        if img is None:
            continue
        assert detect_signal_states(img, [zone])["S"] == expect, f"{path}: expected {expect}"
