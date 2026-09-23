"""Ask answers expose scope, evidence and missing coverage (#198)."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.search.answer_scope import (
    coverage_limitations,
    summarize_identity,
    summarize_scope,
)
from shared.camera_access import ALL


def _src(camera_id, name, started_at, faces=None):
    return {
        "id": str(uuid.uuid4()),
        "camera_id": str(camera_id),
        "camera_name": name,
        "started_at": started_at,
        "person_detections": {"faces": faces or []},
    }


# ── scope ──

def test_scope_reports_cameras_and_evidence_window():
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    srcs = [
        _src(c1, "Porch", "2026-06-11T12:00:00+00:00"),
        _src(c2, "Yard", "2026-06-11T09:00:00+00:00"),
        _src(c1, "Porch", "2026-06-11T15:00:00+00:00"),
    ]
    scope = summarize_scope(srcs)
    assert scope["camera_count"] == 2
    assert {c["name"] for c in scope["cameras_searched"]} == {"Porch", "Yard"}
    assert scope["evidence_from"] == "2026-06-11T09:00:00+00:00"
    assert scope["evidence_to"] == "2026-06-11T15:00:00+00:00"
    assert scope["evidence_count"] == 3


def test_scope_empty_sources():
    scope = summarize_scope([])
    assert scope["camera_count"] == 0
    assert scope["evidence_from"] is None


# ── identity ──

def _resolver(name_by_cluster):
    def resolve(face):
        if face.get("person_name"):
            return face["person_name"]
        cid = face.get("cluster_id")
        return name_by_cluster.get(cid)
    return resolve


def test_identity_splits_matched_uncertain_unidentified():
    cam = uuid.uuid4()
    srcs = [
        _src(cam, "Porch", "2026-06-11T12:00:00+00:00", faces=[
            {"person_name": "Sara"},              # matched
            {"cluster_id": "c-9"},                # matched via cluster name
            {"cluster_id": "c-unknown"},          # recurring unknown -> uncertain
            {},                                   # one-off unknown -> unidentified
        ]),
    ]
    ident = summarize_identity(srcs, _resolver({"c-9": "Ahmed"}))
    assert ident["matched"] == ["Ahmed", "Sara"]
    assert ident["uncertain_identities"] == 1
    assert ident["unidentified_faces"] == 1


def test_identity_dedupes_recurring_clusters():
    cam = uuid.uuid4()
    srcs = [
        _src(cam, "Porch", "2026-06-11T12:00:00+00:00", faces=[{"cluster_id": "x"}]),
        _src(cam, "Porch", "2026-06-11T13:00:00+00:00", faces=[{"cluster_id": "x"}]),
    ]
    ident = summarize_identity(srcs, _resolver({}))
    assert ident["uncertain_identities"] == 1  # same cluster twice = one identity


# ── coverage limitations (DB) ──

class _Res:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._scalar


class _CovDB:
    def __init__(self, cam, *, offline_at=None, oldest=None):
        self.cam = cam
        self.offline_at = offline_at
        self.oldest = oldest

    async def execute(self, stmt):
        text = str(stmt).lower()
        if "camera_status_logs" in text:
            rows = []
            if self.offline_at:
                rows = [SimpleNamespace(camera_id=self.cam, timestamp=self.offline_at)]
            return _Res(rows=rows)
        if "from cameras" in text:
            return _Res(rows=[(self.cam, "Front Door")])
        if "observations" in text:  # min(started_at)
            return _Res(scalar=self.oldest)
        return _Res()


@pytest.mark.asyncio
async def test_offline_camera_surfaces_as_limitation():
    cam = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = _CovDB(cam, offline_at=now - timedelta(hours=2))
    limits = await coverage_limitations(db, allowed=ALL, window_from=now - timedelta(hours=24))
    assert any("Front Door" in m and "offline" in m for m in limits)


@pytest.mark.asyncio
async def test_retention_floor_surfaces_when_window_predates_oldest():
    cam = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = _CovDB(cam, oldest=now - timedelta(hours=1))  # data only 1h old
    limits = await coverage_limitations(db, allowed=ALL, window_from=now - timedelta(hours=24))
    assert any("not retained" in m for m in limits)


@pytest.mark.asyncio
async def test_no_gaps_yields_no_limitations():
    cam = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db = _CovDB(cam, offline_at=None, oldest=now - timedelta(days=30))
    limits = await coverage_limitations(db, allowed=ALL, window_from=now - timedelta(hours=24))
    assert limits == []


# ── answer_question wiring ──

@pytest.mark.asyncio
async def test_answer_question_attaches_scope_identity_limitations(monkeypatch):
    """The no-provider envelope carries the #198 fields."""
    from services.search import query as sq

    cam = uuid.uuid4()
    src = {
        "id": str(uuid.uuid4()), "camera_id": str(cam), "camera_name": "Porch",
        "started_at": "2026-06-11T12:00:00+00:00",
        "person_detections": {"faces": [{"person_name": "Sara"}]},
        "object_detections": {"objects": []}, "vlm_description": "Sara at the door",
    }

    async def _search(*a, **k):
        return [src]

    async def _limits(*a, **k):
        return ["Porch was offline around jun 11, 2:00 pm; that gap could not be checked."]

    async def _no_vlm():
        return None

    monkeypatch.setattr(sq, "search_observations", _search)
    monkeypatch.setattr(sq, "coverage_limitations", _limits)
    monkeypatch.setattr("services.perception.vlm.get_active_provider", _no_vlm, raising=False)
    monkeypatch.setattr(sq, "get_embedding_provider", lambda: _no_vlm(), raising=False)

    class _DB:
        async def execute(self, stmt):
            return _Res(rows=[])

    out = await sq.answer_question(_DB(), "who was at the door?")
    assert out["scope"]["camera_count"] == 1
    assert out["identity"]["matched"] == ["Sara"]
    assert out["limitations"] and "offline" in out["limitations"][0]


@pytest.mark.asyncio
async def test_no_results_with_gap_is_not_called_a_quiet_period(monkeypatch):
    from services.search import query as sq

    async def _search(*a, **k):
        return []

    async def _limits(*a, **k):
        return ["Front Door was offline around jun 11, 2:00 pm; that gap could not be checked."]

    monkeypatch.setattr(sq, "search_observations", _search)
    monkeypatch.setattr(sq, "coverage_limitations", _limits)

    class _DB:
        async def execute(self, stmt):
            return _Res(rows=[])

    out = await sq.answer_question(_DB(), "what happened at 2pm?")
    assert out["sources"] == []
    assert "not a confirmed quiet period" in out["answer"]
    assert out["limitations"]
