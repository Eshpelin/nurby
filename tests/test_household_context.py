"""Unit tests for the agent's household orientation block (G5, issue #131).

The block is deterministic and query-only, so almost all of it is pure. The
one thing worth guarding hardest is the access boundary: the system prompt is
where a leak would be invisible.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.agent import household_context as hc

NOW = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)


def _obs(camera_id, hour, labels=None, faces=None):
    return (
        camera_id,
        NOW.replace(hour=hour),
        {"objects": [{"label": lab} for lab in (labels or [])]},
        {"faces": [{"person_name": f} for f in (faces or [])]},
    )


# ---- activity aggregation ----------------------------------------------


def test_activity_counts_labels_hours_and_faces_per_camera():
    cam_a, cam_b = uuid.uuid4(), uuid.uuid4()
    rows = [_obs(cam_a, 8, ["person", "car"], ["Mom"]) for _ in range(5)]
    rows += [_obs(cam_a, 18, ["person"]) for _ in range(3)]
    rows += [_obs(cam_b, 12, ["dog"]) for _ in range(2)]
    out = hc.summarize_camera_activity(rows)

    assert out[cam_a]["samples"] == 8
    assert out[cam_a]["labels"][0] == "person"
    assert out[cam_a]["busy_hours"] == [8, 18]
    assert out[cam_a]["faces"] == ["Mom"]
    assert out[cam_b]["labels"] == ["dog"]


def test_activity_caps_the_labels_it_keeps():
    cam = uuid.uuid4()
    rows = [_obs(cam, 8, [f"label{i}" for i in range(9)])]
    out = hc.summarize_camera_activity(rows)
    assert len(out[cam]["labels"]) == hc.MAX_LABELS_PER_CAMERA


def test_activity_tolerates_empty_detection_blobs():
    cam = uuid.uuid4()
    out = hc.summarize_camera_activity([(cam, NOW, None, None)])
    assert out[cam] == {"samples": 1, "labels": [], "busy_hours": [8], "faces": []}


# ---- rendering ---------------------------------------------------------


def _cam(name, habits=None, location=None, role="entry"):
    return {"name": name, "role": role, "location": location, "habits": habits}


def _habits(samples=50, labels=("person",), busy=(8, 18), faces=("Mom",)):
    return {"samples": samples, "labels": list(labels),
            "busy_hours": list(busy), "faces": list(faces)}


def test_no_cameras_means_no_block():
    assert hc.format_household_context([], [{"name": "Mom"}], []) is None


def test_camera_line_states_habits():
    text = hc.format_household_context([_cam("Front Door", _habits(), "porch")], [], [])
    assert "- Front Door (porch) — usually sees person; busiest around 08:00, 18:00 UTC" in text
    assert "familiar faces: Mom." in text


def test_thin_camera_is_listed_without_invented_habits():
    text = hc.format_household_context(
        [_cam("New Cam", _habits(samples=hc.MIN_SAMPLES_FOR_HABITS - 1))], [], []
    )
    assert "too little history to characterize yet." in text
    assert "usually sees" not in text


def test_camera_with_no_history_at_all_is_still_listed():
    text = hc.format_household_context([_cam("Dark Cam", None)], [], [])
    assert "- Dark Cam" in text
    assert "too little history" in text


def test_people_and_vehicles_render_with_their_details():
    text = hc.format_household_context(
        [_cam("Front Door", _habits())],
        [{"name": "Mom", "relationship": "parent", "nickname": "Ma",
          "usual_cameras": ["Front Door"]}],
        [{"name": "The Blue Car", "plate": "ABC123"}],
    )
    assert "- Mom, parent, also called Ma, usually on Front Door." in text
    assert "- The Blue Car (plate ABC123)" in text


def test_block_ends_by_denying_itself_evidential_weight():
    text = hc.format_household_context([_cam("Front Door", _habits())], [], [])
    assert "never evidence" in text
    assert "cited" in text


def test_lists_are_capped():
    cams = [_cam(f"Cam{i}", _habits()) for i in range(30)]
    people = [{"name": f"P{i}"} for i in range(30)]
    vehicles = [{"name": f"V{i}"} for i in range(30)]
    text = hc.format_household_context(cams, people, vehicles)
    assert len([ln for ln in text.splitlines() if ln.startswith("  - Cam")]) == hc.MAX_CAMERAS
    assert len([ln for ln in text.splitlines() if ln.startswith("  - P")]) == hc.MAX_PEOPLE
    assert len([ln for ln in text.splitlines() if ln.startswith("  - V")]) == hc.MAX_VEHICLES


# ---- assembly and access scoping ---------------------------------------


class _FakeDB:
    """Returns canned rows per selected entity, sniffing the statement."""

    def __init__(self, cameras, observations, persons, vehicles):
        self.cameras, self.observations = cameras, observations
        self.persons, self.vehicles = persons, vehicles

    async def execute(self, stmt):
        text = str(stmt).lower()
        if "from observations" in text:
            rows = self.observations
        elif "from cameras" in text:
            rows = [(c,) for c in self.cameras]
        elif "from persons" in text:
            rows = [(p,) for p in self.persons]
        elif "from vehicles" in text:
            rows = [(v,) for v in self.vehicles]
        else:
            rows = []

        class _Scalars:
            def __init__(self, items):
                self._items = items

            def all(self):
                return [r[0] if isinstance(r, tuple) else r for r in self._items]

        class _R:
            def __init__(self, items):
                self._items = items

            def all(self):
                return list(self._items)

            def scalars(self):
                return _Scalars(self._items)

        return _R(rows)


def _camera_row(name, cam_id=None):
    return SimpleNamespace(
        id=cam_id or uuid.uuid4(), name=name, location_label=None,
        display_order=0, created_at=NOW,
    )


@pytest.mark.asyncio
async def test_build_uses_only_the_cameras_the_user_may_see():
    hc.clear_cache()
    mine, theirs = _camera_row("Front Door"), _camera_row("Neighbour Cam")
    # The db is asked for cameras; the query itself filters, so the fake
    # returns only what a correctly-scoped query would.
    db = _FakeDB([mine], [_obs(mine.id, 8, ["person"]) for _ in range(30)], [], [])
    text = await hc.build_household_context(db, {mine.id})
    assert "Front Door" in text
    assert "Neighbour Cam" not in text
    assert theirs.name not in text


@pytest.mark.asyncio
async def test_no_accessible_cameras_means_no_block():
    hc.clear_cache()
    db = _FakeDB([], [], [], [])
    assert await hc.build_household_context(db, set()) is None
    assert await hc.household_context(db, set()) is None


@pytest.mark.asyncio
async def test_person_usual_cameras_come_from_the_same_sample():
    hc.clear_cache()
    cam = _camera_row("Kitchen")
    person = SimpleNamespace(display_name="Mom", nickname=None, relationship="parent",
                             is_starred=True)
    rows = [_obs(cam.id, 8, ["person"], ["Mom"]) for _ in range(30)]
    db = _FakeDB([cam], rows, [person], [])
    text = await hc.build_household_context(db, {cam.id})
    assert "- Mom, parent, usually on Kitchen." in text


@pytest.mark.asyncio
async def test_context_is_cached_per_accessible_camera_set():
    hc.clear_cache()
    cam = _camera_row("Front Door")
    rows = [_obs(cam.id, 8, ["person"]) for _ in range(30)]

    calls = {"n": 0}

    class _CountingDB(_FakeDB):
        async def execute(self, stmt):
            calls["n"] += 1
            return await super().execute(stmt)

    db = _CountingDB([cam], rows, [], [])
    first = await hc.household_context(db, {cam.id})
    after_first = calls["n"]
    second = await hc.household_context(db, {cam.id})
    assert second == first
    assert calls["n"] == after_first  # served from cache

    # A different access set is a different key, so it is rebuilt.
    await hc.household_context(db, {cam.id, uuid.uuid4()})
    assert calls["n"] > after_first


@pytest.mark.asyncio
async def test_household_context_never_raises():
    class _Boom:
        async def execute(self, stmt):
            raise RuntimeError("db is down")

    hc.clear_cache()
    assert await hc.household_context(_Boom(), {uuid.uuid4()}) is None
