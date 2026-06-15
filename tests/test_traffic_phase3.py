"""Traffic Phase 3 engine triggers: signal-gated red_light_cross,
crosswalk_violation (vehicle + pedestrian co-presence), and lane_occupancy
(congestion count)."""

from datetime import datetime, timezone

from services.api.routes.rules import _straddle_boxes
from tests._engine_helpers import FakeRule, install_engine

TS = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc).isoformat()
LINE = [[0, 200], [400, 200]]


def _engine(monkeypatch, pattern):
    rule = FakeRule(name="r", trigger_pattern=pattern)
    eng, _ = install_engine(monkeypatch, [rule])
    return eng, rule


def _obj(label, zones, tracker_id=1, bbox=(10, 10, 60, 90)):
    return {"label": label, "confidence": 0.9, "bbox": list(bbox),
            "tracker_id": tracker_id, "zones": zones}


# ── red_light_cross gated by a detected signal zone ────────────────

def _cross_frame(signal_states):
    prev_box, cur_box = _straddle_boxes(LINE[0], LINE[1])
    return {
        "camera_id": "cam-1", "timestamp": TS,
        "tracks": [{"track_id": 1, "label": "car", "bbox": cur_box,
                    "prev_bbox": prev_box, "state": "moving"}],
        "signal_states": signal_states,
    }


def test_signal_red_fires(monkeypatch):
    p = {"type": "red_light_cross", "points": LINE, "signal_zone": "Sig", "label": "car"}
    eng, rule = _engine(monkeypatch, p)
    assert eng._match_trigger(p, _cross_frame({"Sig": "red"}), rule.id, None) is True


def test_signal_green_silent(monkeypatch):
    p = {"type": "red_light_cross", "points": LINE, "signal_zone": "Sig", "label": "car"}
    eng, rule = _engine(monkeypatch, p)
    assert eng._match_trigger(p, _cross_frame({"Sig": "green"}), rule.id, None) is False


def test_signal_missing_state_silent(monkeypatch):
    # signal_zone configured but perception reported nothing for it.
    p = {"type": "red_light_cross", "points": LINE, "signal_zone": "Sig"}
    eng, rule = _engine(monkeypatch, p)
    assert eng._match_trigger(p, _cross_frame({}), rule.id, None) is False


# ── crosswalk_violation ────────────────────────────────────────────

def _cw(monkeypatch, objects):
    p = {"type": "crosswalk_violation", "crosswalk_zone": "CW"}
    eng, rule = _engine(monkeypatch, p)
    frame = {"camera_id": "cam-1", "timestamp": TS,
             "object_detections": {"objects": objects, "count": len(objects)}}
    return eng._match_trigger(p, frame, rule.id, None)


def test_crosswalk_fires_on_copresence(monkeypatch):
    assert _cw(monkeypatch, [_obj("person", ["CW"], 1), _obj("car", ["CW"], 2)]) is True


def test_crosswalk_silent_person_only(monkeypatch):
    assert _cw(monkeypatch, [_obj("person", ["CW"], 1)]) is False


def test_crosswalk_silent_vehicle_only(monkeypatch):
    assert _cw(monkeypatch, [_obj("car", ["CW"], 2)]) is False


def test_crosswalk_silent_vehicle_outside_zone(monkeypatch):
    assert _cw(monkeypatch, [_obj("person", ["CW"], 1), _obj("car", ["Other"], 2)]) is False


# ── lane_occupancy ─────────────────────────────────────────────────

def _lane(monkeypatch, pattern, objects, tracks=None):
    eng, rule = _engine(monkeypatch, pattern)
    frame = {"camera_id": "cam-1", "timestamp": TS,
             "object_detections": {"objects": objects, "count": len(objects)}}
    if tracks is not None:
        frame["tracks"] = tracks
    return eng._match_trigger(pattern, frame, rule.id, None)


def test_lane_fires_at_threshold(monkeypatch):
    p = {"type": "lane_occupancy", "lane_zone": "Lane", "min_vehicles": 3}
    objs = [_obj("car", ["Lane"], i) for i in range(3)]
    assert _lane(monkeypatch, p, objs) is True


def test_lane_silent_below_threshold(monkeypatch):
    p = {"type": "lane_occupancy", "lane_zone": "Lane", "min_vehicles": 3}
    objs = [_obj("car", ["Lane"], i) for i in range(2)]
    assert _lane(monkeypatch, p, objs) is False


def test_lane_requires_stationary(monkeypatch):
    p = {"type": "lane_occupancy", "lane_zone": "Lane", "min_vehicles": 2,
         "require_stationary": True}
    objs = [_obj("car", ["Lane"], i) for i in range(3)]
    moving = [{"track_id": i, "label": "car", "bbox": objs[i]["bbox"],
               "prev_bbox": objs[i]["bbox"], "state": "moving"} for i in range(3)]
    assert _lane(monkeypatch, p, objs, tracks=moving) is False
    parked = [{**t, "state": "stationary"} for t in moving]
    assert _lane(monkeypatch, p, objs, tracks=parked) is True
