"""Unit tests for episode context on the temporal lens (G3, issue #130).

The temporal lens sees three frames. The pipeline already knows the frame
belongs to an incident, and maybe to a cross-camera journey. These cover the
rendering and the assembly; the SQL path is exercised against postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.perception import episode as ep

NOW = datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc)


# ---- rendering ---------------------------------------------------------


def test_no_incident_and_no_journey_renders_nothing():
    assert ep.format_episode_context(None, [], None) is None


def test_incident_block_states_age_and_position():
    text = ep.format_episode_context(
        {"minutes_open": 4, "occurrence_count": 7, "summary": None}, [], None
    )
    assert "began 4 minutes ago" in text
    assert "sighting 7" in text


def test_a_fresh_incident_reads_as_just_now():
    text = ep.format_episode_context(
        {"minutes_open": 0, "occurrence_count": 1, "summary": None}, [], None
    )
    assert "began just now" in text


def test_incident_summary_and_earlier_captions_are_replayed():
    text = ep.format_episode_context(
        {"minutes_open": 3, "occurrence_count": 5, "summary": "A van stopped at the curb."},
        ["A white van pulls up.", "A man steps out.", "ignored, over the cap"],
        None,
    )
    assert "So far: A van stopped at the curb." in text
    assert "Earlier in the episode: A white van pulls up." in text
    assert "Earlier in the episode: A man steps out." in text
    assert "over the cap" not in text


def test_long_captions_are_clipped():
    text = ep.format_episode_context(
        {"minutes_open": 1, "occurrence_count": 2, "summary": "x" * 400}, [], None
    )
    assert "..." in text
    assert "x" * 400 not in text


def test_blank_captions_are_dropped_not_rendered_empty():
    text = ep.format_episode_context(
        {"minutes_open": 1, "occurrence_count": 2, "summary": "   "}, ["  ", ""], None
    )
    assert "So far:" not in text
    assert "Earlier in the episode:" not in text


def test_journey_stops_are_listed_nearest_first_with_the_subject():
    text = ep.format_episode_context(
        None, [], {"stops": [("Front Door", 2), ("Driveway", 9)], "subject": "Mom"}
    )
    assert "The same Mom was seen on: Front Door (2 min ago), Driveway (9 min ago)." in text


def test_journey_without_a_named_subject_stays_generic():
    text = ep.format_episode_context(None, [], {"stops": [("Gate", 0)], "subject": None})
    assert "The same subject was seen on: Gate (just now)." in text


def test_journey_stop_list_is_capped():
    stops = [(f"Cam{i}", i) for i in range(10)]
    text = ep.format_episode_context(None, [], {"stops": stops, "subject": None})
    assert text.count("min ago") + text.count("just now") == ep.MAX_JOURNEY_STOPS


def test_context_always_ends_with_the_instruction():
    text = ep.format_episode_context(
        {"minutes_open": 1, "occurrence_count": 2, "summary": None}, [], None
    )
    assert text.rstrip().endswith("frames do not show.")


# ---- assembly ----------------------------------------------------------


class _FakeDB:
    def __init__(self, objects, rows):
        self._objects = objects
        self._rows = rows

    async def get(self, model, ident):
        return self._objects.get(ident)

    async def execute(self, stmt):
        rows = self._rows

        class _R:
            def all(self):
                return list(rows)

        return _R()


def _incident(**kw):
    base = dict(
        id=uuid.uuid4(),
        started_at=NOW - timedelta(minutes=6),
        occurrence_count=4,
        summary_text=None,
        journey_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_observation_without_an_incident_gets_no_context():
    obs_id = uuid.uuid4()
    obs = SimpleNamespace(id=obs_id, incident_id=None)
    db = _FakeDB({obs_id: obs}, [])
    assert await ep.episode_context(db, obs_id, "cam", NOW) is None


@pytest.mark.asyncio
async def test_incident_context_is_assembled_from_the_row_and_earlier_captions():
    obs_id = uuid.uuid4()
    inc = _incident(summary_text="A van is parked at the curb.")
    obs = SimpleNamespace(id=obs_id, incident_id=inc.id)
    db = _FakeDB({obs_id: obs, inc.id: inc}, [("A white van pulls up.",)])

    text = await ep.episode_context(db, obs_id, "cam", NOW)
    assert "began 6 minutes ago" in text
    assert "sighting 4" in text
    assert "So far: A van is parked at the curb." in text
    assert "Earlier in the episode: A white van pulls up." in text


@pytest.mark.asyncio
async def test_journey_stops_exclude_the_current_camera():
    obs_id = uuid.uuid4()
    cam_here, cam_there = uuid.uuid4(), uuid.uuid4()
    jrn = SimpleNamespace(
        id=uuid.uuid4(),
        subject_kind="person",
        subject_key="Mom",
        segments=[
            {"camera_id": str(cam_here), "camera_name": "Kitchen",
             "last_seen_at": (NOW - timedelta(minutes=1)).isoformat()},
            {"camera_id": str(cam_there), "camera_name": "Front Door",
             "last_seen_at": (NOW - timedelta(minutes=5)).isoformat()},
        ],
    )
    inc = _incident(journey_id=jrn.id)
    obs = SimpleNamespace(id=obs_id, incident_id=inc.id)
    db = _FakeDB({obs_id: obs, inc.id: inc, jrn.id: jrn}, [])

    text = await ep.episode_context(db, obs_id, cam_here, NOW)
    assert "Front Door (5 min ago)" in text
    assert "Kitchen" not in text
    assert "The same Mom" in text


@pytest.mark.asyncio
async def test_malformed_journey_segments_are_skipped_not_fatal():
    obs_id = uuid.uuid4()
    jrn = SimpleNamespace(
        id=uuid.uuid4(),
        subject_kind="vehicle",
        subject_key="ABC123",
        segments=["not a dict", {"camera_name": None}, {"camera_name": "Gate",
                                                        "last_seen_at": "not a date"}],
    )
    inc = _incident(journey_id=jrn.id)
    obs = SimpleNamespace(id=obs_id, incident_id=inc.id)
    db = _FakeDB({obs_id: obs, inc.id: inc, jrn.id: jrn}, [])

    text = await ep.episode_context(db, obs_id, "cam", NOW)
    # The incident half still renders; the unusable journey half is dropped.
    assert "CONTINUES AN EPISODE" in text
    assert "was seen on" not in text


@pytest.mark.asyncio
async def test_episode_context_never_raises():
    class _Boom:
        async def get(self, *a):
            raise RuntimeError("db is down")

    assert await ep.episode_context(_Boom(), uuid.uuid4(), "cam", NOW) is None
