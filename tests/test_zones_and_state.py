"""Named-area zone filters, veto suppression, and stationary-object
filtering: the per-rule false-positive toolkit built on the unified
zone model.
"""

import asyncio

from services.perception.spatial_events import (
    annotate_detection_zones,
    veto_zone_triggered,
)
from services.perception.tracker import (
    STATIONARY_AFTER_TICKS,
    ObjectTracker,
)
from tests._engine_helpers import FakeRule, install_engine

# A 1000x1000 frame. "driveway" covers the left half, "porch" the right.
DRIVEWAY = {"type": "zone", "name": "driveway", "points": [[0, 0], [500, 0], [500, 1000], [0, 1000]]}
PORCH = {"type": "zone", "name": "porch", "points": [[500, 0], [1000, 0], [1000, 1000], [500, 1000]]}
VETO_WALL = {"type": "veto", "name": "wall", "points": [[0, 0], [100, 0], [100, 100], [0, 100]]}


def _det(bbox, label="person", conf=0.9, tid=1):
    return {"label": label, "confidence": conf, "bbox": list(bbox), "tracker_id": tid}


# ── zone membership (bottom-center anchor) ────────────────────────

def test_membership_uses_feet_not_centroid():
    # Person leaning over the driveway line: centroid in driveway (x=480),
    # feet in driveway too; but a person whose bbox straddles with feet on
    # the porch side must belong to the porch.
    d = _det([400, 100, 700, 900])  # anchor (550, 900) -> porch
    annotate_detection_zones([d], [DRIVEWAY, PORCH])
    assert d["zones"] == ["porch"]


def test_membership_multiple_and_none():
    inside = _det([100, 100, 200, 800])  # anchor (150, 800) -> driveway
    outside = _det([100, 100, 200, 800])
    annotate_detection_zones([inside], [DRIVEWAY])
    annotate_detection_zones([outside], [PORCH])
    assert inside["zones"] == ["driveway"]
    assert outside["zones"] == []


def test_loiter_zones_count_as_named_areas():
    loiter = {**DRIVEWAY, "type": "loiter", "loiter_threshold_seconds": 30}
    d = _det([100, 100, 200, 800])
    annotate_detection_zones([d], [loiter])
    assert d["zones"] == ["driveway"]


def test_masks_are_not_named_areas():
    include = {**DRIVEWAY, "type": "include"}
    d = _det([100, 100, 200, 800])
    annotate_detection_zones([d], [include])
    assert d["zones"] == []


# ── veto ──────────────────────────────────────────────────────────

def test_veto_triggers_on_anchor_inside():
    d = _det([10, 10, 80, 90])  # anchor (45, 90) inside wall patch
    assert veto_zone_triggered([d], [VETO_WALL]) == "wall"


def test_veto_quiet_when_clear():
    d = _det([400, 400, 600, 800])
    assert veto_zone_triggered([d], [VETO_WALL]) is None
    assert veto_zone_triggered([d], None) is None


def test_veto_suppresses_rules(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "object_detected", "label": "person"})
    eng, rec = install_engine(monkeypatch, [rule])
    obs = {
        "camera_id": "cam",
        "object_detections": {"objects": [_det([400, 400, 600, 800])], "count": 1},
        "veto_active": True,
        "veto_zone": "wall",
    }
    asyncio.run(eng.evaluate(obs))
    assert rec.call_count == 0


def test_ignore_veto_condition_opts_out(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person"},
        conditions={"ignore_veto": True},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    obs = {
        "camera_id": "cam",
        "object_detections": {"objects": [_det([400, 400, 600, 800])], "count": 1},
        "veto_active": True,
    }
    asyncio.run(eng.evaluate(obs))
    assert rec.call_count == 1


# ── trigger zones filter ──────────────────────────────────────────

def _obs_with_zones(zones):
    d = _det([400, 400, 600, 800])
    d["zones"] = zones
    return {
        "camera_id": "cam",
        "object_detections": {"objects": [d], "count": 1},
    }


def test_zone_scoped_trigger_matches_only_in_zone(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "zones": ["driveway"]},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_obs_with_zones([])))
    asyncio.run(eng.evaluate(_obs_with_zones(["porch"])))
    assert rec.call_count == 0
    asyncio.run(eng.evaluate(_obs_with_zones(["driveway"])))
    assert rec.call_count == 1


# ── stationary tracking ───────────────────────────────────────────

def test_track_goes_stationary_then_moving():
    tracker = ObjectTracker()
    car = {"label": "car", "confidence": 0.9, "bbox": [100, 100, 300, 250]}
    tracker.update([dict(car)])
    tid = list(tracker.tracks)[0]
    assert tracker.tracks[tid].state == "moving"
    # Hold position for the stationary threshold.
    for _ in range(STATIONARY_AFTER_TICKS):
        tracker.update([dict(car)])
    assert tracker.tracks[tid].state == "stationary"
    # Pull away: one real movement flips it back immediately.
    moved = {"label": "car", "confidence": 0.9, "bbox": [200, 100, 400, 250]}
    tracker.update([moved])
    assert tracker.tracks[tid].state == "moving"


def test_object_state_filter_in_engine(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "car", "object_state": "moving"},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    obs = {
        "camera_id": "cam",
        "object_detections": {
            "objects": [_det([100, 100, 300, 250], label="car", tid=6)],
            "count": 1,
        },
        "tracks": [{"track_id": 6, "label": "car", "state": "stationary"}],
    }
    asyncio.run(eng.evaluate(obs))
    assert rec.call_count == 0  # parked car never re-alerts
    obs["tracks"] = [{"track_id": 6, "label": "car", "state": "moving"}]
    asyncio.run(eng.evaluate(obs))
    assert rec.call_count == 1


def test_untracked_detection_counts_as_moving(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "object_detected", "label": "person", "object_state": "moving"},
    )
    eng, rec = install_engine(monkeypatch, [rule])
    d = _det([400, 400, 600, 800])
    d.pop("tracker_id")
    asyncio.run(eng.evaluate({
        "camera_id": "cam",
        "object_detections": {"objects": [d], "count": 1},
        "tracks": [],
    }))
    assert rec.call_count == 1
