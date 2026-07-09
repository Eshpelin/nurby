"""Anonymous scoped share links (services/api/routes/shares.py).

Covers create (token shown once, hash-only storage, expiry default/cap,
view cap), the creator camera-ACL, the unauthenticated resolve/media
endpoints (view counting, cap exhaustion, expiry, revocation), and the
revoke endpoint's owner/admin policy. The suite has no live Postgres, so
the handlers are driven directly against a stub AsyncSession (mirrors
``tests/test_camera_access.py``); queries are matched by compiling them
for the Postgres dialect with literal binds.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.dialects import postgresql

import services.api.routes.shares as shares_mod
from services.api.routes.shares import (
    ShareCreate,
    _share_status,
    create_share,
    list_shares,
    resolve_share,
    revoke_share,
    share_media,
)
from shared.config import settings
from shared.models import ResourceShare

# ── stubs (mirror tests/test_camera_access.py) ──────────────────────


def _user(role: str = "admin") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request(host: str = "203.0.113.9") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=host))


class _Scalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def all(self):  # camera-grant rows: (camera_id,) tuples
        return [(i,) for i in self._items]

    def scalars(self):
        return _Scalars(self._items)

    def scalar_one_or_none(self):
        assert len(self._items) <= 1, "token_hash lookup must be unique"
        return self._items[0] if self._items else None


class FakeDB:
    """Stub AsyncSession: ``get`` serves canned rows keyed by model name,
    ``execute`` answers the two SELECTs the routes issue (camera grants,
    share-by-token-hash / share listing), and ``refresh`` applies the DB
    column defaults an INSERT would."""

    def __init__(self, grants=None):
        self._rows: dict[tuple[str, uuid.UUID], object] = {}
        self.shares: list[ResourceShare] = []
        self.grants = list(grants or [])
        self.commits = 0

    def seed(self, model_name: str, obj) -> object:
        self._rows[(model_name, obj.id)] = obj
        return obj

    def seed_share(self, share: ResourceShare) -> ResourceShare:
        self.shares.append(share)
        return self.seed("ResourceShare", share)

    async def get(self, model, ident):
        return self._rows.get((model.__name__, ident))

    def add(self, obj):
        assert isinstance(obj, ResourceShare)
        self.shares.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "view_count", None) is None:
            obj.view_count = 0
        if getattr(obj, "created_at", None) is None:
            obj.created_at = _now()
        self._rows[("ResourceShare", obj.id)] = obj

    async def execute(self, stmt):
        sql = str(
            stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        low = sql.lower()
        if "user_camera_access" in low:
            return FakeResult(self.grants)
        if "resource_shares" in low:
            if "token_hash =" in low:  # WHERE clause, not the column list
                return FakeResult([s for s in self.shares if s.token_hash in sql])
            return FakeResult(list(self.shares))
        raise AssertionError(f"unexpected query: {sql[:120]}")


def _recording(camera_id=None, file_path="clip.mp4"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        camera_id=camera_id or uuid.uuid4(),
        file_path=file_path,
        started_at=_now() - timedelta(minutes=5),
        duration_seconds=60,
    )


def _observation(camera_id=None, thumbnail_path=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        camera_id=camera_id or uuid.uuid4(),
        thumbnail_path=thumbnail_path,
        started_at=_now() - timedelta(minutes=3),
        vlm_description="a cat on the porch",
    )


def _event(camera_id=None, observation_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        camera_id=camera_id,
        observation_id=observation_id,
        fired_at=_now() - timedelta(minutes=1),
        severity="warning",
    )


def _share(
    kind="recording",
    *,
    token: str | None = None,
    max_views=None,
    view_count=0,
    expires_at=None,
    revoked_at=None,
    created_by=None,
    **resource_ids,
) -> tuple[str, ResourceShare]:
    """A ResourceShare row as the create route would have persisted it."""
    token = token or ("tok-" + uuid.uuid4().hex)
    s = ResourceShare(
        id=uuid.uuid4(),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        kind=kind,
        max_views=max_views,
        view_count=view_count,
        expires_at=expires_at if expires_at is not None else _now() + timedelta(days=7),
        revoked_at=revoked_at,
        created_by_id=created_by,
        created_at=_now(),
        **resource_ids,
    )
    return token, s


async def _create(db, user, **kw):
    return await create_share(ShareCreate(**kw), current_user=user, db=db)


# ── create: token shown once, hash-only storage ─────────────────────


@pytest.mark.asyncio
async def test_create_recording_share_returns_token_once_stores_only_hash():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    out = await _create(db, _user("admin"), kind="recording", resource_id=rec.id)

    raw = out["token"]
    assert out["path"] == f"/share/{raw}"
    assert out["url"].endswith(f"/share/{raw}")
    assert out["kind"] == "recording"

    [stored] = db.shares
    assert stored.recording_id == rec.id
    # Only the SHA-256 of the token is persisted; the raw token appears
    # nowhere on the row.
    assert stored.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in {str(v) for v in vars(stored).values() if v is not None}
    assert db.commits == 1


@pytest.mark.asyncio
async def test_create_observation_and_event_shares_set_matching_fk():
    db = FakeDB()
    obs = db.seed("Observation", _observation())
    out = await _create(db, _user("admin"), kind="observation", resource_id=obs.id)
    assert out["kind"] == "observation"
    assert db.shares[-1].observation_id == obs.id
    assert db.shares[-1].recording_id is None

    ev = db.seed("Event", _event(camera_id=uuid.uuid4()))
    out = await _create(db, _user("admin"), kind="event", resource_id=ev.id)
    assert out["kind"] == "event"
    assert db.shares[-1].event_id == ev.id


@pytest.mark.asyncio
async def test_create_unsupported_kind_400_and_missing_resource_404():
    db = FakeDB()
    with pytest.raises(HTTPException) as ei:
        await _create(db, _user("admin"), kind="camera_live", resource_id=uuid.uuid4())
    assert ei.value.status_code == 400

    for kind in ("recording", "observation", "event"):
        with pytest.raises(HTTPException) as ei:
            await _create(db, _user("admin"), kind=kind, resource_id=uuid.uuid4())
        assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_token_is_urlsafe_and_unguessable_length():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    out = await _create(db, _user("admin"), kind="recording", resource_id=rec.id)
    raw = out["token"]
    # token_urlsafe(32) → 43 chars of base64url alphabet (256 bits).
    assert re.fullmatch(r"[A-Za-z0-9_-]+", raw)
    assert len(raw) >= 43


@pytest.mark.asyncio
async def test_tokens_are_unique_per_share():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    t1 = (await _create(db, _user("admin"), kind="recording", resource_id=rec.id))["token"]
    t2 = (await _create(db, _user("admin"), kind="recording", resource_id=rec.id))["token"]
    assert t1 != t2


# ── create: expiry default 7d, cap 30d, floor 1d, view cap ──────────


@pytest.mark.asyncio
async def test_expiry_defaults_to_seven_days():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    out = await _create(db, _user("admin"), kind="recording", resource_id=rec.id)
    delta = out["expires_at"] - _now()
    assert timedelta(days=6, hours=23) < delta <= timedelta(days=7)


@pytest.mark.asyncio
async def test_expiry_capped_at_thirty_days_and_floored_at_one():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    out = await _create(
        db, _user("admin"), kind="recording", resource_id=rec.id, expires_in_days=365
    )
    assert out["expires_at"] - _now() <= timedelta(days=30)
    assert out["expires_at"] - _now() > timedelta(days=29, hours=23)

    out = await _create(
        db, _user("admin"), kind="recording", resource_id=rec.id, expires_in_days=0
    )
    assert timedelta(0) < out["expires_at"] - _now() <= timedelta(days=1)

    # There is no never-expiring share.
    for s in db.shares:
        assert s.expires_at is not None


@pytest.mark.asyncio
async def test_view_cap_accepted_and_floored_at_one():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    out = await _create(
        db, _user("admin"), kind="recording", resource_id=rec.id, max_views=5
    )
    assert out["max_views"] == 5

    out = await _create(
        db, _user("admin"), kind="recording", resource_id=rec.id, max_views=0
    )
    assert out["max_views"] == 1

    out = await _create(db, _user("admin"), kind="recording", resource_id=rec.id)
    assert out["max_views"] is None  # default: unlimited


# ── create: creator camera ACL ──────────────────────────────────────


@pytest.mark.asyncio
async def test_restricted_creator_cannot_share_foreign_camera():
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    db = FakeDB(grants=[mine])
    rec = db.seed("Recording", _recording(camera_id=theirs))
    with pytest.raises(HTTPException) as ei:
        await _create(db, _user("viewer"), kind="recording", resource_id=rec.id)
    # The route deliberately answers 403 here (resource ids reach this
    # branch only via the creator's own UI listing, which is ACL-scoped).
    assert ei.value.status_code == 403
    assert db.shares == []


@pytest.mark.asyncio
async def test_restricted_creator_can_share_own_camera():
    mine = uuid.uuid4()
    db = FakeDB(grants=[mine])
    rec = db.seed("Recording", _recording(camera_id=mine))
    out = await _create(db, _user("viewer"), kind="recording", resource_id=rec.id)
    assert out["token"]


@pytest.mark.asyncio
async def test_acl_applies_to_observation_and_event_kinds():
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    db = FakeDB(grants=[mine])
    obs = db.seed("Observation", _observation(camera_id=theirs))
    with pytest.raises(HTTPException) as ei:
        await _create(db, _user("operator"), kind="observation", resource_id=obs.id)
    assert ei.value.status_code == 403

    ev = db.seed("Event", _event(camera_id=theirs))
    with pytest.raises(HTTPException) as ei:
        await _create(db, _user("operator"), kind="event", resource_id=ev.id)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_event_acl_falls_back_to_observation_camera():
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    db = FakeDB(grants=[mine])
    obs_ok = db.seed("Observation", _observation(camera_id=mine))
    ev_ok = db.seed("Event", _event(camera_id=None, observation_id=obs_ok.id))
    out = await _create(db, _user("viewer"), kind="event", resource_id=ev_ok.id)
    assert out["token"]

    obs_bad = db.seed("Observation", _observation(camera_id=theirs))
    ev_bad = db.seed("Event", _event(camera_id=None, observation_id=obs_bad.id))
    with pytest.raises(HTTPException) as ei:
        await _create(db, _user("viewer"), kind="event", resource_id=ev_bad.id)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_share_any_camera_without_grant_lookup():
    db = FakeDB(grants=[])  # admin short-circuits to ALL before any grant query
    rec = db.seed("Recording", _recording())
    out = await _create(db, _user("admin"), kind="recording", resource_id=rec.id)
    assert out["token"]


# ── resolve (unauthenticated) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_returns_scoped_metadata_and_counts_view():
    db = FakeDB()
    cam = SimpleNamespace(id=uuid.uuid4(), name="Front Door")
    db.seed("Camera", cam)
    rec = db.seed("Recording", _recording(camera_id=cam.id))
    token, share = _share("recording", recording_id=rec.id, max_views=3, label="porch clip")
    db.seed_share(share)

    out = await resolve_share(token, _request(), db)
    assert out["kind"] == "recording"
    assert out["media_type"] == "video"
    assert out["camera_name"] == "Front Door"
    assert out["label"] == "porch clip"
    assert out["views_left"] == 2
    assert out["media_path"] == f"/api/share/{token}/media"
    # Scoped: no internal ids, paths, or token hash leak to the viewer.
    for verboten in ("id", "recording_id", "camera_id", "file_path", "token_hash", "created_by_id"):
        assert verboten not in out

    assert share.view_count == 1
    assert share.last_accessed_at is not None
    assert share.last_accessed_ip == "203.0.113.9"


@pytest.mark.asyncio
async def test_resolve_observation_and_event_shapes():
    db = FakeDB()
    obs = db.seed("Observation", _observation(thumbnail_path="thumb.jpg"))
    token, share = _share("observation", observation_id=obs.id)
    db.seed_share(share)
    out = await resolve_share(token, _request(), db)
    assert out["media_type"] == "image"
    assert out["description"] == "a cat on the porch"

    ev = db.seed("Event", _event(camera_id=None, observation_id=obs.id))
    token2, share2 = _share("event", event_id=ev.id)
    db.seed_share(share2)
    out = await resolve_share(token2, _request(), db)
    assert out["media_type"] == "image"
    assert out["severity"] == "warning"
    assert out["views_left"] is None  # uncapped share


@pytest.mark.asyncio
async def test_resolve_wrong_token_404():
    db = FakeDB()
    token, share = _share("recording", recording_id=uuid.uuid4())
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await resolve_share("not-the-token", _request(), db)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_view_cap_exhaustion_410():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    token, share = _share("recording", recording_id=rec.id, max_views=2)
    db.seed_share(share)

    await resolve_share(token, _request(), db)
    out = await resolve_share(token, _request(), db)
    assert out["views_left"] == 0
    with pytest.raises(HTTPException) as ei:
        await resolve_share(token, _request(), db)
    assert ei.value.status_code == 410
    assert share.view_count == 2  # the rejected call did not count


@pytest.mark.asyncio
async def test_resolve_expired_410_and_revoked_410():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    token, share = _share(
        "recording", recording_id=rec.id, expires_at=_now() - timedelta(seconds=1)
    )
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await resolve_share(token, _request(), db)
    assert ei.value.status_code == 410
    assert share.view_count == 0

    token2, share2 = _share("recording", recording_id=rec.id, revoked_at=_now())
    db.seed_share(share2)
    with pytest.raises(HTTPException) as ei:
        await resolve_share(token2, _request(), db)
    assert ei.value.status_code == 410


@pytest.mark.asyncio
async def test_resolve_deleted_resource_410():
    db = FakeDB()
    token, share = _share("recording", recording_id=uuid.uuid4())  # row gone
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await resolve_share(token, _request(), db)
    assert ei.value.status_code == 410


# ── revoke ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_revoke_and_it_is_idempotent():
    owner = _user("viewer")
    db = FakeDB()
    _, share = _share("recording", recording_id=uuid.uuid4(), created_by=owner.id)
    db.seed_share(share)

    out = await revoke_share(share.id, current_user=owner, db=db)
    assert out.status == "revoked"
    first = share.revoked_at
    assert first is not None

    out = await revoke_share(share.id, current_user=owner, db=db)
    assert out.status == "revoked"
    assert share.revoked_at == first  # unchanged on the second call


@pytest.mark.asyncio
async def test_admin_can_revoke_anyones_share():
    db = FakeDB()
    _, share = _share("recording", recording_id=uuid.uuid4(), created_by=uuid.uuid4())
    db.seed_share(share)
    out = await revoke_share(share.id, current_user=_user("admin"), db=db)
    assert out.status == "revoked"


@pytest.mark.asyncio
async def test_other_user_cannot_revoke_gets_404():
    db = FakeDB()
    _, share = _share("recording", recording_id=uuid.uuid4(), created_by=uuid.uuid4())
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await revoke_share(share.id, current_user=_user("viewer"), db=db)
    assert ei.value.status_code == 404
    assert share.revoked_at is None


@pytest.mark.asyncio
async def test_revoked_share_media_is_gone_too():
    db = FakeDB()
    rec = db.seed("Recording", _recording())
    token, share = _share("recording", recording_id=rec.id, revoked_at=_now())
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await share_media(token, db)
    assert ei.value.status_code == 410


# ── list ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_never_exposes_token_hash_and_reports_status():
    db = FakeDB()
    _, active = _share("recording", recording_id=uuid.uuid4())
    _, spent = _share("recording", recording_id=uuid.uuid4(), max_views=1, view_count=1)
    db.seed_share(active)
    db.seed_share(spent)
    rows = await list_shares(current_user=_user("admin"), db=db)
    assert {r.status for r in rows} == {"active", "exhausted"}
    for r in rows:
        assert not hasattr(r, "token_hash")
        assert not hasattr(r, "token")


def test_share_status_precedence():
    _, s = _share("recording", recording_id=uuid.uuid4())
    assert _share_status(s) == "active"
    s.max_views, s.view_count = 1, 1
    assert _share_status(s) == "exhausted"
    s.expires_at = _now() - timedelta(seconds=1)
    assert _share_status(s) == "expired"
    s.revoked_at = _now()
    assert _share_status(s) == "revoked"  # revoked wins over everything


# ── media: streams via the normal serve paths ───────────────────────


@pytest.mark.asyncio
async def test_recording_media_serves_file_and_does_not_count_view(tmp_path, monkeypatch):
    root = tmp_path / "recordings"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"\x00mp4")
    monkeypatch.setattr(settings, "recordings_path", str(root))

    db = FakeDB()
    rec = db.seed("Recording", _recording(file_path="clip.mp4"))
    token, share = _share("recording", recording_id=rec.id, max_views=1, view_count=0)
    db.seed_share(share)

    resp = await share_media(token, db)
    assert isinstance(resp, FileResponse)
    assert resp.path == os.path.realpath(str(root / "clip.mp4"))
    assert resp.media_type == "video/mp4"
    # Media is a sub-request of an already-counted page load.
    assert share.view_count == 0

    # And it can be fetched again without burning the single view.
    resp = await share_media(token, db)
    assert isinstance(resp, FileResponse)


@pytest.mark.asyncio
async def test_recording_media_path_outside_root_rejected(tmp_path, monkeypatch):
    root = tmp_path / "recordings"
    root.mkdir()
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"x")
    monkeypatch.setattr(settings, "recordings_path", str(root))

    db = FakeDB()
    rec = db.seed("Recording", _recording(file_path=str(secret)))
    token, share = _share("recording", recording_id=rec.id)
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await share_media(token, db)
    assert ei.value.status_code == 403  # resolve_inside containment


@pytest.mark.asyncio
async def test_observation_and_event_media_serve_thumbnail(tmp_path, monkeypatch):
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    thumb = thumbs / "frame.jpg"
    thumb.write_bytes(b"\xff\xd8jpg")
    monkeypatch.setattr(settings, "thumbnails_path", str(thumbs))

    db = FakeDB()
    obs = db.seed("Observation", _observation(thumbnail_path=str(thumb)))
    token, share = _share("observation", observation_id=obs.id)
    db.seed_share(share)
    resp = await share_media(token, db)
    assert isinstance(resp, FileResponse)
    assert resp.path == os.path.realpath(str(thumb))
    assert resp.media_type == "image/jpeg"

    ev = db.seed("Event", _event(camera_id=None, observation_id=obs.id))
    token2, share2 = _share("event", event_id=ev.id)
    db.seed_share(share2)
    resp = await share_media(token2, db)
    assert isinstance(resp, FileResponse)
    assert resp.path == os.path.realpath(str(thumb))


@pytest.mark.asyncio
async def test_media_404_when_no_thumbnail_or_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "thumbnails_path", str(tmp_path))
    db = FakeDB()
    obs = db.seed("Observation", _observation(thumbnail_path=None))
    token, share = _share("observation", observation_id=obs.id)
    db.seed_share(share)
    with pytest.raises(HTTPException) as ei:
        await share_media(token, db)
    assert ei.value.status_code == 404

    obs2 = db.seed("Observation", _observation(thumbnail_path=str(tmp_path / "gone.jpg")))
    token2, share2 = _share("observation", observation_id=obs2.id)
    db.seed_share(share2)
    with pytest.raises(HTTPException) as ei:
        await share_media(token2, db)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_media_wrong_token_404():
    db = FakeDB()
    with pytest.raises(HTTPException) as ei:
        await share_media("nope", db)
    assert ei.value.status_code == 404
