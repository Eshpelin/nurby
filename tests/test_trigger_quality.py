"""Alert-quality trigger mechanics: confidence gating, multi-frame
persistence, and size/ratio filters.

These are the false-positive defenses (Frigate-style, but per-rule).
Also regression-locks the min_confidence fix: live payloads carry
confidence=None at the observation level, and the condition used to
read only that, so rules with min_confidence could never fire live.
"""

import asyncio

from tests._engine_helpers import FakeRule, install_engine


def _obs(objects, frame_w=1920, frame_h=1080):
    return {
        "camera_id": "cam-1",
        "object_detections": {"objects": objects, "count": len(objects)},
        "frame_width": frame_w,
        "frame_height": frame_h,
        "vlm_description": None,
        "confidence": None,  # live shape: VLM confidence absent at eval time
    }


def _person(conf=0.9, bbox=(100, 100, 200, 400), tracker_id=7):
    return {"label": "person", "confidence": conf, "bbox": list(bbox), "tracker_id": tracker_id}


# ── min_confidence against live payload shape ─────────────────────

def test_min_confidence_fires_on_live_payload(monkeypatch):
    # The regression: observation-level confidence is None live; the
    # condition must gate on the matched detection's YOLO confidence.
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person"},
        conditions={"min_confidence": 0.5},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([_person(conf=0.9)])))
    assert rec.call_count == 1


def test_min_confidence_blocks_weak_detection(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person"},
        conditions={"min_confidence": 0.5},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([_person(conf=0.3)])))
    assert rec.call_count == 0


def test_min_confidence_does_not_block_signal_less_events(monkeypatch):
    # Audio events carry no object confidence; the condition cannot be
    # evaluated and must not silently block.
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "audio_event", "label": "baby_cry"},
        conditions={"min_confidence": 0.5},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate({
        "camera_id": "cam-1",
        "audio_event": {"label": "baby_cry", "score": 0.8},
        "confidence": None,
    }))
    assert rec.call_count == 1


# ── multi-frame persistence ───────────────────────────────────────

def test_min_frames_requires_persistence(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "min_frames": 3},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([_person(tracker_id=7)])))
    asyncio.run(eng.evaluate(_obs([_person(tracker_id=7)])))
    assert rec.call_count == 0  # two frames are not three
    asyncio.run(eng.evaluate(_obs([_person(tracker_id=7)])))
    assert rec.call_count == 1


def test_min_frames_distinct_tracks_do_not_pool(monkeypatch):
    # Three different one-frame objects must not add up to one alert.
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "min_frames": 3},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    for tid in (1, 2, 3):
        asyncio.run(eng.evaluate(_obs([_person(tracker_id=tid)])))
    assert rec.call_count == 0


def test_min_frames_one_behaves_like_before(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "min_frames": 1},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([_person()])))
    assert rec.call_count == 1


def test_min_frames_window_expiry_resets_streak(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "object_detected", "label": "person",
            "min_frames": 2, "within_seconds": 30,
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([_person(tracker_id=9)])))
    # Simulate the first sighting having happened outside the window.
    key, (first, count) = next(iter(eng._persistence.items()))
    eng._persistence[key] = (first - 60, count)
    asyncio.run(eng.evaluate(_obs([_person(tracker_id=9)])))
    assert rec.call_count == 0  # streak restarted, not continued


# ── size / ratio filters ──────────────────────────────────────────

def test_min_area_filter_drops_tiny_detection(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "object_detected", "label": "person", "min_area_pct": 0.01,
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    # 10x10 px in a 1920x1080 frame = 0.0000048 of the frame.
    asyncio.run(eng.evaluate(_obs([_person(bbox=(0, 0, 10, 10))])))
    assert rec.call_count == 0
    # 400x800 px = ~0.15 of the frame.
    asyncio.run(eng.evaluate(_obs([_person(bbox=(0, 0, 400, 800))])))
    assert rec.call_count == 1


def test_max_area_filter_drops_frame_filling_blob(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "object_detected", "label": "person", "max_area_pct": 0.5,
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([_person(bbox=(0, 0, 1920, 1080))])))
    assert rec.call_count == 0


def test_ratio_filter_drops_fence_shadow(monkeypatch):
    # A "dog" 40x wider than tall is a shadow, not a dog.
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "object_detected", "label": "dog",
            "min_ratio": 0.2, "max_ratio": 3.0,
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([
        {"label": "dog", "confidence": 0.8, "bbox": [0, 500, 1600, 540], "tracker_id": 1}
    ])))
    assert rec.call_count == 0
    asyncio.run(eng.evaluate(_obs([
        {"label": "dog", "confidence": 0.8, "bbox": [100, 100, 300, 250], "tracker_id": 2}
    ])))
    assert rec.call_count == 1


def test_geometry_filter_passes_bboxless_detection(monkeypatch):
    # Missing geometry must never block (only bad geometry does).
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "object_detected", "label": "person", "min_area_pct": 0.01,
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs([
        {"label": "person", "confidence": 0.8, "bbox": None, "tracker_id": 3}
    ])))
    assert rec.call_count == 1
