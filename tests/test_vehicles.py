"""Tests for vehicle identity (perception) and the get_vehicles agent tool."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.perception import vehicles as veh


def _run(coro):
    return asyncio.run(coro)


# ── pure helpers ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("abc 123", "ABC123"),
    ("AB-12-CD", "AB12CD"),
    ("  xy ", None),       # < 3 chars
    ("", None),
    (None, None),
])
def test_norm_plate(raw, expected):
    assert veh._norm_plate(raw) == expected


def test_bbox_center_inside():
    vehicle = [100, 100, 300, 300]
    assert veh._bbox_center_inside([180, 250, 260, 290], vehicle) is True   # center 220,270 inside
    assert veh._bbox_center_inside([0, 0, 20, 20], vehicle) is False        # center 10,10 outside
    assert veh._bbox_center_inside([], vehicle) is False                    # malformed


def test_parse_attributes():
    color, make, model = veh._parse_attributes("Red Nissan sedan with tinted windows")
    assert color == "Red"
    assert make == "Nissan"
    # "sedan" is a body word, not a model, so model is omitted.
    assert model is None
    color2, make2, _ = veh._parse_attributes("a white pickup truck")
    assert color2 == "White"
    assert make2 is None


def test_plate_correction_metadata_preserves_historical_evidence():
    from services.api.routes.vehicles import _plate_correction_metadata

    vehicle_id = uuid.uuid4()
    metadata = _plate_correction_metadata(vehicle_id, "OLD123", "NEW456")

    assert metadata == {
        "policy": "human_plate_correction",
        "vehicle_id": str(vehicle_id),
        "previous_plate": "OLD123",
        "corrected_plate": "NEW456",
        "historical_evidence_preserved": True,
    }


def test_merged_episode_key_is_bounded_and_collision_resistant():
    from services.api.routes.vehicles import _merged_episode_key

    key = _merged_episode_key("source", "episode-1", "evidence-1")
    assert key == "merge:source:episode-1"

    long_key = _merged_episode_key("source", "x" * 400, "evidence-1")
    assert len(long_key) == 255
    assert long_key.endswith(":source-evidence:evidence-1")


def test_vehicle_sighting_evidence_preserves_plate_and_detector_metadata():
    from services.api.routes.vehicles import _vehicle_sighting_evidence

    assert _vehicle_sighting_evidence({
        "plate_text": "ABCDXYZ",
        "plate_confidence": 0.91,
        "plate_source": "ocr",
        "confidence": 0.87,
        "identity_key": "ABCDXYZ",
    }) == {
        "plate_text": "ABCDXYZ",
        "plate_confidence": 0.91,
        "plate_source": "ocr",
        "vehicle_confidence": 0.87,
        "identity_key": "ABCDXYZ",
        "identity_kind": "plate",
    }

    assert _vehicle_sighting_evidence({
        "confidence": 0.72,
        "identity_key": "appearance-1",
    })["identity_kind"] == "appearance"


def test_vehicle_merge_rewrites_identity_without_changing_detection_metadata():
    from services.api.routes.vehicles import _rewrite_vehicle_detection_ids

    payload = {
        "vehicles": [
            {
                "vehicle_id": "source",
                "identity_key": "OLD123",
                "plate_text": "OLD123",
                "confidence": 0.81,
                "bbox": [1, 2, 3, 4],
            },
            {"vehicle_id": "other", "identity_key": "OTHER"},
        ],
        "count": 2,
    }

    rewritten = _rewrite_vehicle_detection_ids(payload, "source", "target", "NEW456")

    assert rewritten["vehicles"][0] == {
        "vehicle_id": "target",
        "identity_key": "NEW456",
        "plate_text": "OLD123",
        "confidence": 0.81,
        "bbox": [1, 2, 3, 4],
    }
    assert rewritten["vehicles"][1] == payload["vehicles"][1]
    assert payload["vehicles"][0]["vehicle_id"] == "source"


def test_vehicle_merge_scope_requires_every_affected_camera():
    from services.api.routes.vehicles import _camera_set_is_scoped
    from shared.camera_access import ALL

    assert _camera_set_is_scoped(["camera-a"], {"camera-a"}) is True
    assert _camera_set_is_scoped(["camera-a", "camera-b"], {"camera-a"}) is False
    assert _camera_set_is_scoped(["camera-a", "camera-b"], ALL) is True
    assert _camera_set_is_scoped([], set()) is True


def test_vehicle_scope_follows_visible_later_observation(monkeypatch):
    from services.api.routes.vehicles import _vehicle_in_scope

    visible = uuid.uuid4()
    vehicle_id = uuid.uuid4()
    vehicle = MagicMock(id=vehicle_id, first_camera_id=uuid.uuid4())
    observation = MagicMock(
        camera_id=visible,
        vehicle_detections={"vehicles": [{"vehicle_id": str(vehicle_id)}]},
    )

    class Result:
        def scalars(self):
            return self

        def all(self):
            return [observation]

    class DB:
        async def execute(self, _stmt):
            return Result()

    async def allowed(_user, _db):
        return {visible}

    monkeypatch.setattr("services.api.routes.vehicles.allowed_camera_ids", allowed)
    user = MagicMock(role="viewer", camera_access_mode="selected")
    assert _run(_vehicle_in_scope(vehicle, user, DB())) is True


def test_vehicle_list_visibility_uses_any_allowed_observation():
    from services.api.routes.vehicles import _visible_vehicle_ids

    visible_camera = uuid.uuid4()
    vehicle_id = uuid.uuid4()
    observation = MagicMock(
        camera_id=visible_camera,
        vehicle_detections={"vehicles": [{"vehicle_id": str(vehicle_id)}]},
    )

    class Result:
        def scalars(self):
            return self

        def all(self):
            return [observation]

    class DB:
        async def execute(self, _stmt):
            return Result()

    visible = _run(_visible_vehicle_ids(DB(), {visible_camera}))
    assert visible == {str(vehicle_id)}


# ── identify_vehicles ────────────────────────────────────────────────

def _exec_none():
    res = MagicMock()
    res.scalar_one_or_none.return_value = None
    return res


def _stub_db():
    db = AsyncMock()
    added: list = []
    db.add = MagicMock(side_effect=lambda o: added.append(o))

    async def _flush():
        for o in added:
            if getattr(o, "id", None) is None:
                o.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=_flush)
    db.execute = AsyncMock(return_value=_exec_none())
    db._added = added
    return db


def test_identify_creates_vehicle_for_plated_detection():
    db = _stub_db()
    cam = uuid.uuid4()
    ts = datetime.now(timezone.utc)
    detections = [
        {"label": "car", "confidence": 0.9, "bbox": [100, 100, 300, 300]},
        {"label": "license_plate", "confidence": 0.8, "bbox": [180, 250, 260, 290], "plate_text": "ABC 123"},
    ]
    vd, jobs = _run(veh.identify_vehicles(db, cam, detections, ts))

    assert vd["count"] == 1
    entry = vd["vehicles"][0]
    assert entry["plate_text"] == "ABC123"
    assert entry["vehicle_id"] is not None
    assert entry["identity_key"] == "ABC123"
    # A new Vehicle row was created and queued for a description.
    assert len(db._added) == 1
    assert db._added[0].identity_key == "ABC123"
    assert db._added[0].license_plate == "ABC123"
    assert len(jobs) == 1


def test_identify_plateless_vehicle_gets_no_identity():
    db = _stub_db()
    detections = [{"label": "car", "confidence": 0.9, "bbox": [100, 100, 300, 300]}]
    vd, jobs = _run(veh.identify_vehicles(db, uuid.uuid4(), detections, datetime.now(timezone.utc)))

    assert vd["count"] == 1
    entry = vd["vehicles"][0]
    assert entry["plate_text"] is None
    assert entry["vehicle_id"] is None     # plateless -> no persistent identity
    assert db._added == []                  # no Vehicle row created
    assert jobs == []


def test_identify_returns_none_without_vehicles():
    db = _stub_db()
    detections = [{"label": "chair", "confidence": 0.9, "bbox": [0, 0, 10, 10]}]
    vd, jobs = _run(veh.identify_vehicles(db, uuid.uuid4(), detections, datetime.now(timezone.utc)))
    assert vd is None and jobs == []


def test_identify_existing_plate_updates_not_inserts():
    db = _stub_db()
    existing = MagicMock()
    existing.id = uuid.uuid4()
    existing.sighting_count = 4
    existing.vehicle_type = "car"
    existing.description_status = "done"
    existing.description = "Red car"
    res = MagicMock()
    res.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=res)

    detections = [
        {"label": "car", "confidence": 0.9, "bbox": [100, 100, 300, 300]},
        {"label": "license_plate", "bbox": [180, 250, 260, 290], "plate_text": "ABC123"},
    ]
    vd, jobs = _run(veh.identify_vehicles(db, uuid.uuid4(), detections, datetime.now(timezone.utc)))

    assert vd["vehicles"][0]["vehicle_id"] == str(existing.id)
    assert existing.sighting_count == 5     # incremented
    assert db._added == []                  # reused, not inserted
    assert jobs == []                       # already described


# ── get_vehicles agent tool ──────────────────────────────────────────

def _fake_vehicle(**kw):
    v = MagicMock()
    v.id = uuid.uuid4()
    v.display_name = kw.get("display_name", "Plate ABC123")
    v.license_plate = kw.get("license_plate", "ABC123")
    v.vehicle_type = kw.get("vehicle_type", "car")
    v.color = kw.get("color")
    v.make = kw.get("make")
    v.model = kw.get("model")
    v.description = kw.get("description")
    v.first_seen_at = datetime.now(timezone.utc)
    v.last_seen_at = datetime.now(timezone.utc)
    v.sighting_count = kw.get("sighting_count", 3)
    return v


def _tool_ctx(vehicles):
    vehicle_ids = [str(vehicle.id) for vehicle in vehicles]
    camera_id = uuid.uuid4()

    def result_for(stmt):
        res = MagicMock()
        statement = str(stmt).lower()
        if "from cameras" in statement:
            res.all.return_value = [(camera_id,)]
        elif "vehicle_detections" in statement:
            res.all.return_value = [(
                {"vehicles": [{"vehicle_id": vehicle_id} for vehicle_id in vehicle_ids]},
            )]
        else:
            scal = MagicMock()
            scal.all.return_value = vehicles
            res.scalars.return_value = scal
        return res

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=result_for)
    user = MagicMock()
    user.role = "admin"
    return {"db": db, "user": user}


def test_get_vehicles_returns_all():
    from services.agent.tools import get_vehicles
    ctx = _tool_ctx([_fake_vehicle(), _fake_vehicle(license_plate="XYZ789")])
    out = _run(get_vehicles(ctx))
    assert out["count"] == 2


def test_get_vehicles_filters_by_plate():
    from services.agent.tools import get_vehicles
    ctx = _tool_ctx([_fake_vehicle(license_plate="ABC123"), _fake_vehicle(license_plate="XYZ789")])
    out = _run(get_vehicles(ctx, plate="xyz"))
    assert out["count"] == 1
    assert out["vehicles"][0]["license_plate"] == "XYZ789"


def test_get_vehicles_filters_by_query():
    from services.agent.tools import get_vehicles
    ctx = _tool_ctx([
        _fake_vehicle(description="Red Nissan sedan", make="Nissan", color="Red"),
        _fake_vehicle(description="White truck", vehicle_type="truck"),
    ])
    out = _run(get_vehicles(ctx, query="nissan"))
    assert out["count"] == 1
    assert out["vehicles"][0]["make"] == "Nissan"


# ── per-camera plateless toggle resolver ──────────────────────────────

class _Cam:
    def __init__(self, scene_mode="indoor", plateless_reid_enabled=None):
        self.scene_mode = scene_mode
        self.plateless_reid_enabled = plateless_reid_enabled


def test_plateless_auto_on_indoor():
    from services.perception.vehicles import plateless_reid_on
    assert plateless_reid_on(_Cam("indoor", None)) is True


def test_plateless_auto_off_outdoor():
    from services.perception.vehicles import plateless_reid_on
    assert plateless_reid_on(_Cam("outdoor", None)) is False


def test_plateless_explicit_overrides_scene():
    from services.perception.vehicles import plateless_reid_on
    assert plateless_reid_on(_Cam("outdoor", True)) is True   # force on outdoors
    assert plateless_reid_on(_Cam("indoor", False)) is False  # force off indoors


def test_plateless_none_camera_defaults_on():
    from services.perception.vehicles import plateless_reid_on
    assert plateless_reid_on(None) is True
