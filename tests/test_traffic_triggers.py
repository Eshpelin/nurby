"""Traffic-monitoring rule triggers: plate blacklist/whitelist, parking-spot
reservation, and wrong-way driving. All run on the existing rule_data
(vehicle_detections + tracks + zone annotation), no new CV.
"""

import asyncio

from services.api.routes.rules import _synthesize_observation_for_trigger
from tests._engine_helpers import FakeRule, install_engine


def _fire_count(monkeypatch, pattern, data):
    rule = FakeRule(name="r", trigger_pattern=pattern)
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(data))
    return rec.call_count


def _vehicles(*entries):
    return {"vehicle_detections": {"vehicles": list(entries), "count": len(entries)}}


# ── plate_list (blacklist / whitelist) ─────────────────────────────

def test_blacklist_fires_on_listed_plate(monkeypatch):
    p = {"type": "plate_list", "mode": "blacklist", "plates": ["ABC123", "XYZ"]}
    data = _vehicles({"plate_text": "abc 123", "bbox": [0, 0, 10, 10]})  # normalized match
    assert _fire_count(monkeypatch, p, data) == 1


def test_blacklist_ignores_unlisted_plate(monkeypatch):
    p = {"type": "plate_list", "mode": "blacklist", "plates": ["ABC123"]}
    data = _vehicles({"plate_text": "ZZZ999", "bbox": [0, 0, 10, 10]})
    assert _fire_count(monkeypatch, p, data) == 0


def test_whitelist_fires_on_unlisted_plate(monkeypatch):
    p = {"type": "plate_list", "mode": "whitelist", "plates": ["FAM111", "FAM222"]}
    data = _vehicles({"plate_text": "STRANGER9", "bbox": [0, 0, 10, 10]})
    assert _fire_count(monkeypatch, p, data) == 1


def test_whitelist_silent_on_authorized_plate(monkeypatch):
    p = {"type": "plate_list", "mode": "whitelist", "plates": ["FAM111"]}
    data = _vehicles({"plate_text": "FAM 111", "bbox": [0, 0, 10, 10]})
    assert _fire_count(monkeypatch, p, data) == 0


def test_whitelist_skips_unreadable_plate_by_default(monkeypatch):
    p = {"type": "plate_list", "mode": "whitelist", "plates": ["FAM111"]}
    data = _vehicles({"plate_text": None, "bbox": [0, 0, 10, 10]})
    assert _fire_count(monkeypatch, p, data) == 0


def test_whitelist_flags_unreadable_when_required(monkeypatch):
    p = {"type": "plate_list", "mode": "whitelist", "plates": ["FAM111"], "require_plate": False}
    data = _vehicles({"plate_text": None, "bbox": [0, 0, 10, 10]})
    assert _fire_count(monkeypatch, p, data) == 1


# ── parking_violation ──────────────────────────────────────────────

def test_parking_fires_on_intruder_in_spot(monkeypatch):
    p = {"type": "parking_violation", "spot_zone": "Spot A", "reserved_plates": ["MINE1"]}
    data = _vehicles({"plate_text": "OTHER9", "bbox": [0, 0, 10, 10], "zones": ["Spot A"]})
    assert _fire_count(monkeypatch, p, data) == 1


def test_parking_silent_for_reserved_vehicle(monkeypatch):
    p = {"type": "parking_violation", "spot_zone": "Spot A", "reserved_plates": ["MINE1"]}
    data = _vehicles({"plate_text": "MINE1", "bbox": [0, 0, 10, 10], "zones": ["Spot A"]})
    assert _fire_count(monkeypatch, p, data) == 0


def test_parking_silent_when_vehicle_elsewhere(monkeypatch):
    p = {"type": "parking_violation", "spot_zone": "Spot A", "reserved_plates": ["MINE1"]}
    data = _vehicles({"plate_text": "OTHER9", "bbox": [0, 0, 10, 10], "zones": ["Driveway"]})
    assert _fire_count(monkeypatch, p, data) == 0


def test_parking_empty_reserved_alerts_any_vehicle(monkeypatch):
    p = {"type": "parking_violation", "spot_zone": "Spot A", "reserved_plates": []}
    data = _vehicles({"plate_text": "ANYONE", "bbox": [0, 0, 10, 10], "zones": ["Spot A"]})
    assert _fire_count(monkeypatch, p, data) == 1


def test_parking_require_stationary_skips_moving(monkeypatch):
    p = {"type": "parking_violation", "spot_zone": "Spot A", "reserved_plates": [],
         "require_stationary": True}
    data = _vehicles({"plate_text": "X", "bbox": [0, 0, 50, 50], "zones": ["Spot A"]})
    data["tracks"] = [{"track_id": 1, "label": "car", "bbox": [0, 0, 50, 50],
                       "prev_bbox": None, "state": "moving"}]
    assert _fire_count(monkeypatch, p, data) == 0
    data["tracks"][0]["state"] = "stationary"
    assert _fire_count(monkeypatch, p, data) == 1


# ── wrong_way ──────────────────────────────────────────────────────

def test_wrong_way_fires_against_allowed_direction(monkeypatch):
    # A horizontal line; crossing top→bottom vs bottom→top picks direction.
    pattern = {"type": "wrong_way", "points": [[0, 100], [200, 100]],
               "allowed_direction": "in", "label": "car"}
    # Use the synthesizer to build a guaranteed wrong-way crossing.
    data = _synthesize_observation_for_trigger(pattern, None)
    assert _fire_count(monkeypatch, pattern, data) == 1


def test_wrong_way_silent_on_correct_direction(monkeypatch):
    pattern = {"type": "wrong_way", "points": [[0, 100], [200, 100]],
               "allowed_direction": "in", "label": "car"}
    # Build a crossing, then flip prev/cur so it goes the allowed way.
    data = _synthesize_observation_for_trigger(pattern, None)
    tr = data["tracks"][0]
    tr["bbox"], tr["prev_bbox"] = tr["prev_bbox"], tr["bbox"]
    assert _fire_count(monkeypatch, pattern, data) == 0


def test_wrong_way_label_filter(monkeypatch):
    pattern = {"type": "wrong_way", "points": [[0, 100], [200, 100]],
               "allowed_direction": "in", "label": "car"}
    data = _synthesize_observation_for_trigger(pattern, None)
    data["tracks"][0]["label"] = "person"  # not a car
    assert _fire_count(monkeypatch, pattern, data) == 0


# ── dry-run synthesis sanity (rule tester) ─────────────────────────

def test_synthesis_blacklist_matches(monkeypatch):
    p = {"type": "plate_list", "mode": "blacklist", "plates": ["BANNED1"]}
    data = _synthesize_observation_for_trigger(p, None)
    assert _fire_count(monkeypatch, p, data) == 1


def test_synthesis_whitelist_matches(monkeypatch):
    p = {"type": "plate_list", "mode": "whitelist", "plates": ["FAM111"]}
    data = _synthesize_observation_for_trigger(p, None)
    assert _fire_count(monkeypatch, p, data) == 1


def test_synthesis_parking_matches(monkeypatch):
    p = {"type": "parking_violation", "spot_zone": "Spot A", "reserved_plates": ["MINE1"]}
    data = _synthesize_observation_for_trigger(p, None)
    assert _fire_count(monkeypatch, p, data) == 1
