"""On-demand recording annotation: lane mapping, segment coalescing, cache
key, bbox scaling, and a synthetic-video render smoke test."""

import os

import pytest

import services.api.recording_annotate as ra


# ── pure helpers ──

def test_classify_lane():
    assert ra.classify_lane("person") == "human"
    assert ra.classify_lane("CAT") == "pet"
    assert ra.classify_lane("dog") == "pet"
    for v in ("car", "truck", "bus", "motorcycle", "bicycle"):
        assert ra.classify_lane(v) == "vehicle"
    assert ra.classify_lane("umbrella") is None
    assert ra.classify_lane(None) is None
    assert ra.classify_lane("") is None


def test_lanes_in_filters_by_confidence():
    dets = [
        {"label": "person", "confidence": 0.95},
        {"label": "car", "confidence": 0.4},          # below threshold
        {"label": "cat", "confidence": 0.85},
        {"label": "umbrella", "confidence": 0.99},     # not a priority lane
    ]
    assert ra.lanes_in(dets, 0.8) == {"human", "pet"}
    assert ra.lanes_in(dets, 0.3) == {"human", "pet", "vehicle"}
    assert ra.lanes_in([], 0.8) == set()


def test_build_object_segments_holds_until_next_and_coalesces():
    # human present at 0 and 2 (contiguous -> one segment); pet only at 4.
    samples = [(0.0, {"human"}), (2.0, {"human"}), (4.0, {"pet"})]
    segs = ra.build_object_segments(samples, duration=6.0)
    human = [s for s in segs if s["lane"] == "human"]
    pet = [s for s in segs if s["lane"] == "pet"]
    assert len(human) == 1 and human[0]["start"] == 0.0 and human[0]["end"] == 4.0
    assert len(pet) == 1 and pet[0]["start"] == 4.0 and pet[0]["end"] == 6.0


def test_build_object_segments_gap_splits():
    # human at 0 (holds to 1), gap, human again at 5 -> two segments.
    samples = [(0.0, {"human"}), (1.0, set()), (5.0, {"human"})]
    segs = [s for s in ra.build_object_segments(samples, duration=6.0) if s["lane"] == "human"]
    assert len(segs) == 2


def test_build_object_segments_empty():
    assert ra.build_object_segments([], 10.0) == []


def test_cache_key_varies_by_opts(tmp_path):
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"\x00" * 32)
    k1 = ra._cache_key(str(src), {"boxes": True, "strip": False})
    k2 = ra._cache_key(str(src), {"boxes": True, "strip": True})
    assert k1 != k2
    assert k1 == ra._cache_key(str(src), {"boxes": True, "strip": False})  # stable


def test_scale_bbox():
    assert ra._scale_bbox([10, 20, 30, 40], 2.0, 0.5) == (20, 10, 60, 20)


# ── synthetic render smoke test ──

def test_render_annotated_smoke(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    # Build a tiny 64x48 source clip (10 black frames @ 10fps).
    src = str(tmp_path / "src.mp4")
    writer = cv2.VideoWriter(src, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
    if not writer.isOpened():
        pytest.skip("mp4v writer unavailable in this build")
    for _ in range(10):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()
    if os.path.getsize(src) == 0:
        pytest.skip("could not encode synthetic source clip")

    # Redirect the cache into tmp so we don't touch the real recordings dir.
    monkeypatch.setattr(ra, "CACHE_DIR", str(tmp_path / "annotated"))

    observations = [
        {"offset": 0.2, "vlm_description": "A person walks in",
         "object_detections": {"objects": [{"label": "person", "bbox": [5, 5, 30, 44], "confidence": 0.9}]}},
        {"offset": 0.6, "vlm_description": "A car passes",
         "object_detections": {"objects": [{"label": "car", "bbox": [20, 10, 60, 40], "confidence": 0.85}]}},
    ]
    opts = {"boxes": True, "captions": True, "strip": True, "min_conf": 0.8}
    out = ra.render_annotated(src, observations, opts, cam_w=64, cam_h=48)
    assert os.path.exists(out) and os.path.getsize(out) > 0

    # Second call hits the cache (same path returned, no error).
    assert ra.render_annotated(src, observations, opts, cam_w=64, cam_h=48) == out
