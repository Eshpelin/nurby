"""Speaker attribution for audio transcripts (#227).

Two layers:

* ``attribute_by_video`` -- the pure Tier A heuristic. A transcript is
  attributed to a named person only when exactly one such person covers
  at least 60% of the segment window on the same camera. Otherwise the
  segment stays ``ambiguous``.
* the transcripts API -- surfaces the attributed name and offers a
  correction affordance that records an ``AudioAuditLog`` row and marks
  the source ``manual``, so a household fix is durable and auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routes import transcripts
from services.perception.audio.speaker_video import attribute_by_video
from shared import auth
from shared.database import get_db

T0 = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)


def _obs(camera_id, start_offset, end_offset, faces):
    return SimpleNamespace(
        camera_id=camera_id,
        started_at=T0 + timedelta(seconds=start_offset),
        ended_at=(T0 + timedelta(seconds=end_offset)) if end_offset is not None else None,
        person_detections={"faces": faces},
    )


class _ObsDB:
    """Minimal async DB whose ``execute`` returns a fixed observation
    set. ``attribute_by_video`` only issues one SELECT."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        rows = list(self._rows)

        class _R:
            def scalars(self_inner):
                return SimpleNamespace(all=lambda: rows)

        return _R()


@pytest.mark.asyncio
async def test_single_dominant_named_person_is_attributed():
    cam = uuid.uuid4()
    alice = str(uuid.uuid4())
    # Alice visible for the whole 10s segment.
    db = _ObsDB([
        _obs(cam, 0, 10, [{"person_id": alice, "person_name": "Alice"}]),
    ])
    result = await attribute_by_video(db, cam, T0, T0 + timedelta(seconds=10))
    assert result.source == "video"
    assert str(result.person_id) == alice
    assert result.confidence is not None and result.confidence >= 0.6


@pytest.mark.asyncio
async def test_below_coverage_threshold_stays_ambiguous():
    cam = uuid.uuid4()
    alice = str(uuid.uuid4())
    # Alice only present for 4 of 10 seconds -> under the 60% bar.
    db = _ObsDB([
        _obs(cam, 0, 4, [{"person_id": alice, "person_name": "Alice"}]),
    ])
    result = await attribute_by_video(db, cam, T0, T0 + timedelta(seconds=10))
    assert result.source == "ambiguous"
    assert result.person_id is None


@pytest.mark.asyncio
async def test_two_dominant_people_stay_ambiguous():
    cam = uuid.uuid4()
    alice = str(uuid.uuid4())
    bob = str(uuid.uuid4())
    # Both cover the whole window -> we refuse to guess.
    db = _ObsDB([
        _obs(cam, 0, 10, [
            {"person_id": alice, "person_name": "Alice"},
            {"person_id": bob, "person_name": "Bob"},
        ]),
    ])
    result = await attribute_by_video(db, cam, T0, T0 + timedelta(seconds=10))
    assert result.source == "ambiguous"
    assert result.person_id is None


@pytest.mark.asyncio
async def test_unnamed_cluster_faces_do_not_attribute():
    cam = uuid.uuid4()
    # A cluster-only face (no person_name) must not anchor a name.
    db = _ObsDB([
        _obs(cam, 0, 10, [{"cluster_id": str(uuid.uuid4())}]),
    ])
    result = await attribute_by_video(db, cam, T0, T0 + timedelta(seconds=10))
    assert result.source == "ambiguous"
    assert result.person_id is None


@pytest.mark.asyncio
async def test_open_observation_can_anchor_attribution():
    cam = uuid.uuid4()
    alice = str(uuid.uuid4())
    # ended_at is None (still open) -> treated as ongoing through segment end.
    db = _ObsDB([
        _obs(cam, 0, None, [{"person_id": alice, "person_name": "Alice"}]),
    ])
    result = await attribute_by_video(db, cam, T0, T0 + timedelta(seconds=10))
    assert result.source == "video"
    assert str(result.person_id) == alice


# --------------------------------------------------------------------------
# Route: serialization + correction affordance.
# --------------------------------------------------------------------------


class _RouteDB:
    """Fake async session for the transcripts route. Tracks added rows
    (e.g. AudioAuditLog), serves ``get`` from a keyed store, and answers
    the person-name SELECT the serializer issues."""

    def __init__(self, transcript, person=None):
        self.transcript = transcript
        self.person = person
        self.added: list = []
        self.committed = False

    async def get(self, model, ident):
        name = getattr(model, "__name__", "")
        if name == "Transcript":
            return self.transcript if self.transcript.id == ident else None
        if name == "Person":
            if self.person is not None and self.person.id == ident:
                return self.person
            return None
        if name == "User":
            return SimpleNamespace(id=ident, role="admin", is_active=True, camera_access_mode="all")
        return None

    async def execute(self, _stmt):
        people = [self.person] if self.person is not None else []

        class _R:
            def scalars(self_inner):
                return SimpleNamespace(all=lambda: people)

        return _R()

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        return None


def _make_transcript(camera_id, **overrides):
    base = dict(
        id=uuid.uuid4(),
        camera_id=camera_id,
        audio_capture_id=None,
        started_at=T0,
        ended_at=T0 + timedelta(seconds=5),
        text="hello there",
        original_text="hello there",
        text_edited=False,
        language="en",
        provider="mock",
        model="fixture-v1",
        confidence=0.9,
        no_speech_prob=0.01,
        filtered=False,
        speaker_person_id=None,
        speaker_source=None,
        speaker_confidence=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _client(db, monkeypatch):
    app = FastAPI()
    app.include_router(transcripts.router, prefix="/transcripts")

    async def session():
        yield db

    app.dependency_overrides[get_db] = session

    # Camera-scope guards are exercised elsewhere; here we let everything
    # through so the test stays focused on attribution behavior.
    from shared import camera_access

    async def _all_scope(*_a, **_k):
        return camera_access.ALL

    async def _require(*_a, **_k):
        return None

    monkeypatch.setattr(transcripts, "allowed_camera_ids", _all_scope)
    monkeypatch.setattr(transcripts, "require_camera_in_scope", _require)

    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {auth.create_access_token(uuid.uuid4())}"
    return client


def test_get_transcript_surfaces_speaker_name(monkeypatch):
    cam = uuid.uuid4()
    person = SimpleNamespace(id=uuid.uuid4(), display_name="Alice", nickname=None)
    tx = _make_transcript(
        cam,
        speaker_person_id=person.id,
        speaker_source="video",
        speaker_confidence=0.8,
    )
    db = _RouteDB(tx, person)
    client = _client(db, monkeypatch)

    resp = client.get(f"/transcripts/{tx.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["speaker_name"] == "Alice"
    assert body["speaker_source"] == "video"
    assert body["speaker_person_id"] == str(person.id)


def test_set_speaker_records_manual_source_and_audit(monkeypatch):
    cam = uuid.uuid4()
    person = SimpleNamespace(id=uuid.uuid4(), display_name="Bob", nickname="Bobby")
    tx = _make_transcript(cam)
    db = _RouteDB(tx, person)
    client = _client(db, monkeypatch)

    resp = client.patch(
        f"/transcripts/{tx.id}/speaker",
        json={"speaker_person_id": str(person.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["speaker_name"] == "Bobby"  # nickname wins
    assert body["speaker_source"] == "manual"
    assert body["speaker_confidence"] == 1.0
    # Attribution mutated the row and wrote exactly one audit entry.
    assert tx.speaker_person_id == person.id
    audits = [a for a in db.added if type(a).__name__ == "AudioAuditLog"]
    assert len(audits) == 1
    assert audits[0].field == "transcript_speaker"
    assert audits[0].new_value == str(person.id)
    assert db.committed is True


def test_clear_speaker_returns_to_unattributed(monkeypatch):
    cam = uuid.uuid4()
    person = SimpleNamespace(id=uuid.uuid4(), display_name="Bob", nickname=None)
    tx = _make_transcript(
        cam,
        speaker_person_id=person.id,
        speaker_source="video",
        speaker_confidence=0.7,
    )
    db = _RouteDB(tx, person)
    client = _client(db, monkeypatch)

    resp = client.patch(
        f"/transcripts/{tx.id}/speaker",
        json={"speaker_person_id": None},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["speaker_person_id"] is None
    assert body["speaker_name"] is None
    assert body["speaker_source"] is None
    assert tx.speaker_person_id is None
    audits = [a for a in db.added if type(a).__name__ == "AudioAuditLog"]
    assert len(audits) == 1
    assert audits[0].old_value == str(person.id)
    assert audits[0].new_value is None


def test_set_speaker_unknown_person_is_404(monkeypatch):
    cam = uuid.uuid4()
    tx = _make_transcript(cam)
    db = _RouteDB(tx, person=None)
    client = _client(db, monkeypatch)

    resp = client.patch(
        f"/transcripts/{tx.id}/speaker",
        json={"speaker_person_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
