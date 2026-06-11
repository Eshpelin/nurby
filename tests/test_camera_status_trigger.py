"""camera_offline / camera_online trigger coverage.

These triggers fire on synthetic camera availability events (published by
ingestion on a real status transition, consumed by CameraStatusWatcher),
never on real observations. The reverse also holds: availability events
must not fire observation triggers, including the catch-all "any".
"""

import asyncio

import pytest

from services.ingestion.stream import classify_status_transition
from services.perception.camera_status_watcher import CameraStatusWatcher
from tests._engine_helpers import FakeRule, install_engine

CAM = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def _offline_event(camera_id: str = CAM) -> dict:
    return {
        "event_kind": "camera_status",
        "camera_id": camera_id,
        "camera_name": "Porch",
        "camera_status": "offline",
        "previous_status": "recording",
        "status_reason": "connection timed out",
        "timestamp": "2026-06-11T00:00:00+00:00",
    }


def _online_event(camera_id: str = CAM) -> dict:
    ev = _offline_event(camera_id)
    ev["camera_status"] = "online"
    ev["previous_status"] = "offline"
    ev["status_reason"] = "stream connected"
    return ev


# ── trigger matching ──────────────────────────────────────────────

def test_camera_offline_fires_on_offline_event(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "camera_offline"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_offline_event()))
    assert rec.call_count == 1


def test_camera_offline_ignores_online_event(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "camera_offline"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_online_event()))
    assert rec.call_count == 0


def test_camera_online_fires_on_recovery(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "camera_online"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_online_event()))
    assert rec.call_count == 1


def test_camera_filter_in_pattern(monkeypatch):
    rule = FakeRule(
        name="r", trigger_pattern={"type": "camera_offline", "camera_id": CAM}
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_offline_event(OTHER)))
    assert rec.call_count == 0
    asyncio.run(eng.evaluate(_offline_event(CAM)))
    assert rec.call_count == 1


def test_any_trigger_does_not_fire_on_status_event(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "any"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_offline_event()))
    assert rec.call_count == 0


def test_object_trigger_does_not_fire_on_status_event(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "object_detected"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_offline_event()))
    assert rec.call_count == 0


def test_offline_trigger_does_not_fire_on_real_observation(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "camera_offline"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(
        eng.evaluate(
            {
                "camera_id": CAM,
                "object_detections": {"objects": [{"label": "person"}]},
            }
        )
    )
    assert rec.call_count == 0


# ── ingestion edge classification ─────────────────────────────────

@pytest.mark.parametrize(
    "status,previous,expected",
    [
        ("offline", "recording", "offline"),
        ("offline", "live", "offline"),
        ("offline", None, "offline"),  # dead camera at startup still alerts
        ("offline", "offline", None),  # no repeated edges while it stays down
        ("live", "offline", "online"),
        ("recording", "offline", "online"),
        ("live", None, None),  # normal startup is not a recovery
        ("recording", "live", None),  # live<->recording flips are not edges
        ("live", "recording", None),
    ],
)
def test_classify_status_transition(status, previous, expected):
    assert classify_status_transition(status, previous) == expected


# ── stream entry shaping ──────────────────────────────────────────

def test_watcher_event_shape():
    fields = {
        "camera_id": CAM,
        "camera_name": "Porch",
        "camera_status": "offline",
        "previous_status": "recording",
        "reason": "connection timed out",
        "timestamp": "2026-06-11T00:00:00+00:00",
    }
    ev = CameraStatusWatcher._to_event(fields)
    assert ev["event_kind"] == "camera_status"
    assert ev["camera_status"] == "offline"
    assert ev["camera_id"] == CAM
    assert ev["status_reason"] == "connection timed out"
