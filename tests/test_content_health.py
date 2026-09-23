"""Camera content-health: frozen / obscured detection (#212)."""

import numpy as np

from services.ingestion.content_health import ContentHealthDetector


def _feed(det, *, frame_hash, variance, start, step, count):
    """Feed `count` samples `step` seconds apart; return the last transition."""
    last = None
    t = start
    for _ in range(count):
        r = det.update(frame_hash, variance, t)
        if r is not None:
            last = r
        t += step
    return last, t


# ── freeze ──

def test_identical_frames_trip_frozen_after_window():
    det = ContentHealthDetector(freeze_seconds=180, detect_obscure=False)
    # A healthy scene has plenty of variance; only the hash being identical
    # matters for freeze.
    transitions = []
    t = 0.0
    for _ in range(200):  # 200s at 1s steps, hash never changes
        r = det.update(frame_hash=42, variance=500.0, now=t)
        if r:
            transitions.append((r, t))
        t += 1.0
    assert transitions and transitions[0][0] == "degraded"
    # First degraded fires at ~180s after the first identical repeat.
    assert 179 <= transitions[0][1] <= 182


def test_quiet_scene_does_not_trip_freeze():
    """A quiet scene still has tiny frame-to-frame changes -> hash varies ->
    never frozen, even over a long window."""
    det = ContentHealthDetector(freeze_seconds=180, detect_obscure=False)
    t = 0.0
    tripped = False
    for i in range(400):
        # hash changes every sample, as a real (even quiet) scene would.
        if det.update(frame_hash=i, variance=500.0, now=t):
            tripped = True
        t += 1.0
    assert tripped is False


def test_freeze_then_recovery():
    det = ContentHealthDetector(freeze_seconds=60, recover_seconds=10, detect_obscure=False)
    # Freeze.
    edge, t = _feed(det, frame_hash=7, variance=500.0, start=0.0, step=1.0, count=70)
    assert edge == "degraded"
    assert det.is_degraded is True
    # Now frames change again; after recover_seconds -> recovered.
    rec = None
    for i in range(20):
        r = det.update(frame_hash=1000 + i, variance=500.0, now=t)
        if r:
            rec = r
        t += 1.0
    assert rec == "recovered"
    assert det.is_degraded is False


# ── obscuration ──

def test_low_variance_trips_obscured():
    det = ContentHealthDetector(obscure_variance=8.0, obscure_seconds=120, detect_freeze=False)
    transitions = []
    t = 0.0
    for i in range(200):
        # Changing hash (not frozen) but near-uniform frame (covered lens).
        r = det.update(frame_hash=i, variance=2.0, now=t)
        if r:
            transitions.append((r, t))
        t += 1.0
    assert transitions and transitions[0][0] == "degraded"
    assert det.reason == "obscured"


def test_normal_variance_does_not_trip_obscured():
    det = ContentHealthDetector(obscure_variance=8.0, obscure_seconds=120, detect_freeze=False)
    t = 0.0
    tripped = any(
        det.update(frame_hash=i, variance=300.0, now=(t := t + 1.0)) for i in range(300)
    )
    assert tripped is False


def test_toggles_disable_paths():
    # Freeze disabled: identical frames never trip.
    det = ContentHealthDetector(detect_freeze=False, detect_obscure=True, obscure_seconds=10)
    t = 0.0
    for _ in range(50):
        assert det.update(frame_hash=1, variance=999.0, now=t) is None
        t += 1.0


def test_persistent_scene_change_can_trip_when_opted_in():
    det = ContentHealthDetector(
        detect_freeze=False,
        detect_obscure=False,
        detect_scene_change=True,
        scene_change_distance=4,
        scene_change_seconds=10,
    )
    assert det.update(frame_hash=0b0000, variance=500.0, now=0.0) is None
    assert det.update(frame_hash=0b1111, variance=500.0, now=5.0) is None
    assert det.update(frame_hash=0b1111, variance=500.0, now=10.0) is None
    assert det.update(frame_hash=0b1111, variance=500.0, now=15.0) == "degraded"
    assert det.reason == "scene_changed"


# ── feature helper ──

def test_frame_features_distinguishes_uniform_from_textured():
    from services.ingestion.stream import _frame_features

    uniform = np.full((64, 64, 3), 127, dtype=np.uint8)
    _, var_uniform = _frame_features(uniform)
    assert var_uniform < 1.0  # covered lens -> ~0 variance

    textured = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    h1, var_textured = _frame_features(textured)
    assert var_textured > var_uniform
    # Identical frames hash identically; a different frame does not.
    h2, _ = _frame_features(textured)
    assert h1 == h2
