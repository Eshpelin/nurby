"""Tests for guardian fall detection heuristics and debounce."""

import uuid

import pytest

from services.perception import guardian_fall as gf

DEP = str(uuid.uuid4())


class _Cam:
    id = uuid.uuid4()
    motion_zones = None


def _face(pid, bbox):
    return {"person_id": pid, "person_name": "Inara", "bbox": bbox}


def setup_function():
    gf.reset_state()


def test_looks_fallen_geometry():
    # wide, low box = fallen
    assert gf.looks_fallen([100, 700, 500, 900], frame_h=1000) is True
    # tall, upright box = not fallen
    assert gf.looks_fallen([100, 100, 250, 700], frame_h=1000) is False
    # wide but high in frame (e.g. a shelf) = not fallen
    assert gf.looks_fallen([100, 50, 500, 200], frame_h=1000) is False
    assert gf.looks_fallen(None, 1000) is False


def test_person_for_fall_attributes_face_inside_body():
    body = [100, 700, 500, 900]
    faces = [_face(DEP, [300, 780, 360, 840])]  # face centre inside body
    assert gf.person_for_fall(body, faces) == (DEP, "Inara")
    # face outside the fallen body is not attributed
    assert gf.person_for_fall(body, [_face(DEP, [10, 10, 40, 40])]) is None


@pytest.mark.asyncio
async def test_process_debounces_until_hold_then_fires_once(monkeypatch):
    calls = []

    async def fake_emit(name, camera):
        calls.append(name)

    monkeypatch.setattr(gf, "_safe_emit", fake_emit)
    cam = _Cam()
    body = [100, 700, 500, 900]
    faces = [_face(DEP, [300, 780, 360, 840])]

    # t=0: fallen detected but hold not met -> no alert
    await gf.process(cam, [body], faces, 1000, now=0.0)
    assert calls == []
    # t=2: still within hold
    await gf.process(cam, [body], faces, 1000, now=2.0)
    assert calls == []
    # t=6: past HOLD_SECONDS -> one alert
    await gf.process(cam, [body], faces, 1000, now=6.0)
    assert calls == ["Inara"]
    # t=8: still fallen -> no duplicate
    await gf.process(cam, [body], faces, 1000, now=8.0)
    assert calls == ["Inara"]


@pytest.mark.asyncio
async def test_process_no_alert_without_recognised_face(monkeypatch):
    calls = []
    monkeypatch.setattr(gf, "_safe_emit", lambda *a: _noop(calls))
    cam = _Cam()
    body = [100, 700, 500, 900]
    # fallen body but no face -> never attributed, never alerts
    await gf.process(cam, [body], [], 1000, now=0.0)
    await gf.process(cam, [body], [], 1000, now=10.0)
    assert calls == []


async def _noop(calls):
    return None
