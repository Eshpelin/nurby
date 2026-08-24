"""One incident per subject, not one per group (issue #145).

Two people walking together used to produce a single incident signed
"Ahmed,Sara", which is a different subject than "Ahmed" and therefore
fragmented both of their histories. These tests pin the fan-out: each
subject in frame gets its own incident and its own membership row, and
the strongest rung is the one mirrored onto the observation.
"""

import asyncio
import uuid
from types import SimpleNamespace

from services.perception import incident_tracker as it


def _track(tid, *, state, person_id=None, person_name=None, body_cluster_id=None):
    return {
        "tracker_id": tid,
        "bbox": [0, 0, 10, 20],
        "person_id": person_id,
        "person_name": person_name,
        "body_cluster_id": body_cluster_id,
        "state": state,
    }


def _face(*, person_name=None, cluster_id=None):
    return {
        "bbox": [1, 1, 5, 5],
        "person_id": "p-1" if person_name else None,
        "person_name": person_name,
        "match_distance": 0.4,
        "cluster_id": cluster_id,
    }


class _FakeDB:
    """Collects what assign_incidents adds. No query surface needed:
    _assign_one is stubbed in these tests, so nothing reaches SQL."""

    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None


def _observation(person_detections, object_detections=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        person_detections=person_detections,
        object_detections=object_detections,
        started_at=None,
        thumbnail_path=None,
    )


def _cam(enabled=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        incident_tracking_enabled=enabled,
        incident_idle_seconds=600,
        name="Hallway",
    )


def _stub_assign_one(monkeypatch):
    """Give every distinct signature its own stable incident id, and
    record the order the assignments were attempted in."""
    ids = {}
    calls = []

    async def fake(db, cam, observation, kind, key, bound_by):
        calls.append((kind, key, bound_by))
        return ids.setdefault((kind, key), uuid.uuid4())

    monkeypatch.setattr(it, "_assign_one", fake)
    return calls


# ---- the core regression -------------------------------------------------


def test_two_people_get_two_incidents(monkeypatch):
    calls = _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({
        "faces": [_face(person_name="Ahmed"), _face(person_name="Sara")],
        "bodies": [],
        "tracks": [],
    })

    linked = asyncio.run(it.assign_incidents(db, _cam(), obs))

    assert len(linked) == 2
    assert len(set(linked)) == 2, "each subject needs its own incident"
    assert [c[1] for c in calls] == ["Ahmed", "Sara"]
    assert not any("," in c[1] for c in calls), "keys must never be joined"


def test_membership_rows_name_each_subject(monkeypatch):
    _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({
        "faces": [_face(person_name="Ahmed"), _face(person_name="Sara")],
        "bodies": [],
        "tracks": [],
    })

    asyncio.run(it.assign_incidents(db, _cam(), obs))

    rows = db.added
    assert [r.subject_key for r in rows] == ["Ahmed", "Sara"]
    assert all(r.observation_id == obs.id for r in rows)
    assert all(r.subject_kind == "person" for r in rows)


def test_exactly_one_row_is_primary(monkeypatch):
    _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({
        "faces": [_face(person_name="Sara"), _face(cluster_id="fc-1")],
        "bodies": [{"bbox": [0, 0, 1, 1], "body_cluster_id": "bc-1"}],
        "tracks": [],
    })

    linked = asyncio.run(it.assign_incidents(db, _cam(), obs))

    primaries = [r for r in db.added if r.is_primary]
    assert len(primaries) == 1
    # The strongest rung wins, and it is the one the caller mirrors onto
    # Observation.incident_id.
    assert primaries[0].subject_kind == "person"
    assert primaries[0].incident_id == linked[0]


def test_primary_follows_what_linked_not_what_was_attempted(monkeypatch):
    """If the strongest subject fails to link, the next one that does
    becomes primary. Otherwise the observation points at nothing."""
    async def fake(db, cam, observation, kind, key, bound_by):
        return None if kind == "person" else uuid.uuid4()

    monkeypatch.setattr(it, "_assign_one", fake)
    db = _FakeDB()
    obs = _observation({
        "faces": [_face(person_name="Ahmed"), _face(cluster_id="fc-2")],
        "bodies": [],
        "tracks": [],
    })

    linked = asyncio.run(it.assign_incidents(db, _cam(), obs))

    assert len(linked) == 1
    assert len(db.added) == 1
    assert db.added[0].is_primary is True
    assert db.added[0].subject_kind == "cluster"


# ---- ordering and evidence ----------------------------------------------


def test_linked_ids_follow_the_identity_ladder(monkeypatch):
    calls = _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({
        "faces": [_face(person_name="Sara"), _face(cluster_id="fc-1")],
        "bodies": [{"bbox": [0, 0, 1, 1], "body_cluster_id": "bc-1"}],
        "tracks": [],
    })

    asyncio.run(it.assign_incidents(db, _cam(), obs))

    assert [c[0] for c in calls] == ["person", "cluster", "body"]


def test_bound_by_is_carried_onto_the_membership_row(monkeypatch):
    _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({
        "faces": [],
        "bodies": [],
        "tracks": [_track(1, state="body", body_cluster_id="bc-7")],
    })

    asyncio.run(it.assign_incidents(db, _cam(), obs))

    assert db.added[0].bound_by == "body"
    assert db.added[0].subject_kind == "body"


# ---- fallbacks -----------------------------------------------------------


def test_scene_with_no_people_still_gets_one_signature(monkeypatch):
    calls = _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation(None, {"objects": [{"label": "car"}]})

    linked = asyncio.run(it.assign_incidents(db, _cam(), obs))

    assert len(linked) == 1
    assert calls == [("object", "car", None)]


def test_tracking_disabled_links_nothing(monkeypatch):
    _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({"faces": [_face(person_name="Ahmed")], "tracks": []})

    assert asyncio.run(it.assign_incidents(db, _cam(enabled=False), obs)) == []
    assert db.added == []


def test_assign_incident_wrapper_returns_the_primary(monkeypatch):
    _stub_assign_one(monkeypatch)
    db = _FakeDB()
    obs = _observation({
        "faces": [_face(person_name="Ahmed"), _face(person_name="Sara")],
        "tracks": [],
    })

    primary = asyncio.run(it.assign_incident(db, _cam(), obs))
    primary_rows = [r for r in db.added if r.is_primary]

    assert primary == primary_rows[0].incident_id


def test_assign_incident_wrapper_returns_none_when_off(monkeypatch):
    _stub_assign_one(monkeypatch)
    obs = _observation({"faces": [_face(person_name="Ahmed")], "tracks": []})
    assert asyncio.run(it.assign_incident(_FakeDB(), _cam(enabled=False), obs)) is None


# ---- observation_signatures (pure) ---------------------------------------


def test_observation_signatures_one_entry_per_subject():
    pd = {
        "faces": [_face(person_name="Ahmed"), _face(person_name="Sara")],
        "bodies": [],
        "tracks": [],
    }
    assert it.observation_signatures(pd, None) == [
        ("person", "Ahmed", "face"),
        ("person", "Sara", "face"),
    ]


def test_observation_signatures_falls_back_to_motion():
    assert it.observation_signatures(None, None) == [("motion", "motion", None)]


def test_observation_signatures_falls_back_to_unknown_face():
    pd = {"faces": [_face()], "bodies": [], "tracks": []}
    assert it.observation_signatures(pd, None) == [("unknown", "unknown", "face")]


def test_the_same_person_twice_in_frame_is_one_subject():
    """A held track and its matched face are the same person. Fanning out
    would double-count them into two incidents."""
    pd = {
        "faces": [_face(person_name="Ahmed")],
        "bodies": [],
        "tracks": [_track(1, state="person", person_id="p-1", person_name="Ahmed")],
    }
    assert len(it.observation_signatures(pd, None)) == 1
