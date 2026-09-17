"""Camera isolation at HTTP boundaries and in every search fallback query."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.api.routes import audio, conversations, digests, notifications, search, summaries, timeline, transcripts
from services.search import query, scan
from shared import auth
from shared.database import get_db
from shared.camera_access import ALL
from shared.models import ApiKey, Camera, Conversation, Observation, Summary, Transcript, User, UserCameraAccess


class EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class ScopeDB:
    def __init__(self):
        self.camera = uuid.uuid4()
        self.foreign_camera = uuid.uuid4()
        self.user = SimpleNamespace(id=uuid.uuid4(), role="viewer", is_active=True, camera_access_mode="selected")
        self.statements = []
        self.row = SimpleNamespace(camera_id=self.foreign_camera, clip_path="/secret.mp4")
        self.commit = AsyncMock()

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()
        self.statements.append(sql)
        if "from user_camera_access" in sql:
            return SimpleNamespace(all=lambda: [(self.camera,)])
        return EmptyResult()

    async def stream(self, stmt):
        return await self.execute(stmt)

    async def get(self, model, ident):
        return self.user if model is User else self.row


@pytest.fixture
def http():
    db = ScopeDB()
    app = FastAPI()
    for name, module in (
        ("audio", audio), ("conversations", conversations), ("digests", digests),
        ("notifications", notifications), ("search", search), ("summaries", summaries),
        ("timeline", timeline), ("transcripts", transcripts),
    ):
        app.include_router(module.router, prefix=f"/{name}")

    async def session():
        yield db

    app.dependency_overrides[get_db] = session
    # Exercise the real JWT and active-user dependencies for every HTTP call.
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {auth.create_access_token(db.user.id)}"
        yield client, db


@pytest.mark.parametrize("path,tables", [
    ("/search", ["observations"]),
    ("/search/union", ["observations", "transcripts", "conversations", "summaries"]),
    ("/timeline", ["observations", "transcripts"]),
    ("/summaries", ["summaries"]),
    ("/conversations", ["conversations"]),
    ("/transcripts", ["transcripts"]),
    ("/transcripts/export.csv", ["transcripts"]),
    ("/digests", ["digest_entries"]),
    ("/search/digests", ["digest_entries"]),
    ("/search/digests/latest", ["digest_entries"]),
    ("/notifications", ["notifications"]),
    ("/notifications/count", ["notifications"]),
])
def test_list_queries_scope_before_pagination(http, path, tables):
    client, db = http
    response = client.get(path)
    assert response.status_code == 200, response.text
    for table in tables:
        statements = [s for s in db.statements if f"from {table}" in s]
        assert statements, (path, db.statements)
        for sql in statements:
            predicate = f"{table}.camera_id in ('{db.camera}')"
            assert predicate in sql
            if " limit " in sql:
                assert sql.index(predicate) < sql.index(" limit ")
    assert not any("from household_mode_changes" in s for s in db.statements)


@pytest.mark.parametrize("path", ["summaries", "transcripts", "conversations", "audio", "conversations/{id}/clip"])
def test_foreign_detail_and_media_are_hidden(http, path):
    client, db = http
    ident = uuid.uuid4()
    route = path.format(id=ident) if "{id}" in path else f"{path}/{ident}"
    response = client.get(f"/{route}")
    assert response.status_code == 404, response.text
    # Fake rows deliberately lack content/file attributes: no serialization or
    # filesystem lookup is possible before the authorization check.
    db.commit.assert_not_called()


@pytest.mark.parametrize("mode", ["none", "selected"])
def test_explicit_foreign_camera_cannot_trigger_summary(http, mode):
    client, db = http
    db.user.camera_access_mode = mode
    response = client.post("/summaries/run", json={"camera_id": str(db.foreign_camera)})
    assert response.status_code == 404


def test_mark_all_read_only_updates_authorized_notifications(http):
    client, db = http
    assert client.post("/notifications/read-all").status_code == 200
    statement = next(s for s in db.statements if s.startswith("update notifications"))
    assert f"notifications.camera_id in ('{db.camera}')" in statement
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("factory", [auth.create_mobile_pair_code, auth.create_guardian_claim_token])
def test_single_purpose_tokens_are_not_login_or_media_credentials(http, factory):
    client, db = http
    token = factory(db.user.id)
    assert auth.decode_access_token(token) is None
    client.headers.pop("Authorization")
    assert client.get(f"/audio/{uuid.uuid4()}", params={"token": token}).status_code == 401
    assert client.get("/summaries", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_media_query_token_checks_active_user_and_camera(http):
    client, db = http
    token = auth.create_access_token(db.user.id)
    client.headers.pop("Authorization")
    path = f"/audio/{uuid.uuid4()}"
    assert client.get(path).status_code == 401
    assert client.get(path, params={"token": token}).status_code == 404
    db.user.is_active = False
    assert client.get(path, params={"token": token}).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("fn", [query.search_observations, query.search_transcripts, query.search_summaries, query.search_conversations])
@pytest.mark.parametrize("embedding", [None, [0.0] * 384])
async def test_every_search_strategy_includes_camera_filter(monkeypatch, fn, embedding):
    monkeypatch.setattr(query, "_embed_query", AsyncMock(return_value=embedding))
    db = ScopeDB()
    assert await fn(db, query="dog", allowed={db.camera}) == []
    assert db.statements
    for sql in db.statements:
        assert f"camera_id in ('{db.camera}')" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("fn", [query.search_observations, query.search_transcripts, query.search_summaries, query.search_conversations])
async def test_no_camera_search_never_queries_or_embeds(monkeypatch, fn):
    embed = AsyncMock(side_effect=AssertionError("must not embed"))
    monkeypatch.setattr(query, "_embed_query", embed)
    db = ScopeDB()
    assert await fn(db, query="private name", allowed=set()) == []
    assert db.statements == []


@pytest.mark.asyncio
async def test_people_fallback_is_scoped():
    db = ScopeDB()
    await query._recent_people_observations(db, allowed={db.camera})
    assert f"observations.camera_id in ('{db.camera}')" in db.statements[0]


def test_scan_poll_hides_retained_results_after_revocation(http, monkeypatch):
    client, db = http
    registry = scan.ScanRegistry()
    monkeypatch.setattr(scan, "get_registry", lambda: registry)
    job = registry.create(str(db.user.id), "dog")
    job.camera_scope = {db.camera}
    assert client.get(f"/search/scan/{job.id}").status_code == 200
    db.user.camera_access_mode = "none"
    assert client.get(f"/search/scan/{job.id}").status_code == 404


@pytest.mark.asyncio
async def test_scan_revocation_stops_before_frame_or_cache(monkeypatch):
    import shared.database

    db = ScopeDB()
    job = scan.ScanJob(id="test", user_id=str(db.user.id), query="dog", camera_scope={db.camera})
    sessions = 0

    @asynccontextmanager
    async def session():
        nonlocal sessions
        sessions += 1
        if sessions > 1:
            db.user.camera_access_mode = "none"
        yield db

    search_mock = AsyncMock(return_value=[{"id": str(uuid.uuid4()), "camera_id": str(db.camera)}])
    cache = AsyncMock(side_effect=AssertionError("cache read after revocation"))
    loader = Mock(side_effect=AssertionError("frame read after revocation"))
    monkeypatch.setattr(shared.database, "async_session", session)
    monkeypatch.setattr(query, "search_observations", search_mock)
    monkeypatch.setattr(scan, "get_cached_grounding", cache)
    await scan.run_scan(job, camera_id=None, time_from=None, time_to=None, max_frames=1,
                        allowed={db.camera}, request_user_id=db.user.id, client=Mock(), frame_loader=loader)
    assert job.status == "error"
    assert job.error == "Scan access changed"
    assert job.scanned == 0
    assert search_mock.call_args.kwargs["allowed"] == {db.camera}
    cache.assert_not_called()
    loader.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("model,fn,extra", [
    (Observation, query.search_observations, {}),
    (Transcript, query.search_transcripts, {"text": "hello", "provider": "test", "model": "test"}),
    (Summary, query.search_summaries, {"kind": "periodic", "trigger_reason": "test", "summary_text": "hello"}),
    (Conversation, query.search_conversations, {"finalized": True, "summary_text": "hello"}),
])
async def test_real_queries_return_only_granted_camera_before_limit(model, fn, extra):
    """Real SQLite rows verify positive access and prevent post-limit filtering.

    PostgreSQL-only vector and regex branches are covered by compilation above.
    """
    engine = create_engine("sqlite://")
    Camera.__table__.create(engine)
    model.__table__.create(engine)
    own, foreign = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as session:
            session.add_all([Camera(id=own, name="Own", stream_url="test"),
                             Camera(id=foreign, name="Foreign", stream_url="test")])
            for i, camera in enumerate((own, foreign)):
                values = dict(camera_id=camera, started_at=now + timedelta(minutes=i), **extra)
                if model is not Observation:
                    values["ended_at"] = now + timedelta(minutes=i + 1)
                if model is Conversation:
                    values["ended_at_provisional"] = values["ended_at"]
                session.add(model(**values))
            session.commit()

            class AsyncAdapter:
                async def execute(self, stmt):
                    return session.execute(stmt)

            db = AsyncAdapter()
            restricted = await fn(db, allowed={own}, limit=1)
            assert [r["camera_id"] for r in restricted] == [str(own)]
            assert [r["camera_name"] for r in restricted] == ["Own"]
            unrestricted = await fn(db, allowed=ALL, limit=1)
            assert [r["camera_id"] for r in unrestricted] == [str(foreign)]
            assert await fn(db, allowed={own}, camera_id=foreign) == []
            assert await fn(db, allowed=set()) == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["selected", "none", "all"])
def test_timeline_narration_receives_effective_scope(http, monkeypatch, mode):
    from services.perception import daily_digest

    client, db = http
    db.user.camera_access_mode = mode
    narrate = AsyncMock(return_value={"summary": "test", "notable_events": []})
    monkeypatch.setattr(daily_digest, "narrate_window", narrate)
    response = client.post("/timeline/summarize", json={
        "window_start": "2026-09-16T10:00:00Z", "window_end": "2026-09-16T11:00:00Z",
    })
    assert response.status_code == 200
    expected = {db.camera} if mode == "selected" else set() if mode == "none" else None
    assert narrate.call_args.kwargs["camera_ids"] == expected


@pytest.mark.parametrize("method,path,body", [
    ("patch", "transcripts/{id}", {"text": "changed"}),
    ("delete", "transcripts/{id}", None),
    ("post", "conversations/{id}/reinterpret", {}),
    ("patch", "notifications/{id}/read", None),
])
def test_foreign_evidence_cannot_be_changed(http, method, path, body):
    client, db = http
    response = client.request(method, "/" + path.format(id=uuid.uuid4()), json=body)
    assert response.status_code == 404, response.text
    db.commit.assert_not_called()


def test_media_api_key_checks_current_owner_scope(http, monkeypatch):
    client, db = http
    resolver = AsyncMock(return_value=db.user)
    monkeypatch.setattr(auth, "_user_from_api_key", resolver)
    response = client.get(f"/audio/{uuid.uuid4()}", headers={"Authorization": "Bearer nrb_test"})
    assert response.status_code == 404
    resolver.assert_awaited_once_with("nrb_test", db)


@pytest.mark.parametrize("header", [True, False])
def test_authorized_audio_streams_with_header_or_query_token(http, monkeypatch, tmp_path, header):
    client, db = http
    clip = tmp_path / "clip.ogg"
    clip.write_bytes(b"test audio")
    monkeypatch.setattr(audio.settings, "audio_storage_path", str(tmp_path))
    db.row = SimpleNamespace(camera_id=db.camera, file_path=str(clip))
    params = {}
    if not header:
        client.headers.pop("Authorization")
        params["token"] = auth.create_access_token(db.user.id)
    response = client.get(f"/audio/{uuid.uuid4()}", params=params)
    assert response.status_code == 200
    assert response.content == b"test audio"


def test_foreign_camera_cannot_be_grounded(http):
    client, db = http
    response = client.post("/search/locate-now", json={"camera_id": str(db.foreign_camera), "prompt": "dog"})
    assert response.status_code == 404
    assert not any("from observations" in s for s in db.statements)


@pytest.mark.parametrize("mode", ["selected", "none"])
def test_ask_passes_effective_scope_to_answer_pipeline(http, monkeypatch, mode):
    client, db = http
    db.user.camera_access_mode = mode
    answer = AsyncMock(return_value={"answer": "No evidence", "sources": []})
    monkeypatch.setattr(search, "answer_question", answer)
    response = client.post("/search/ask", json={"question": "Who visited?"})
    assert response.status_code == 200, response.text
    assert answer.call_args.kwargs["allowed"] == ({db.camera} if mode == "selected" else set())


def test_two_users_database_grants_and_api_key_revoke_immediately():
    """Real auth, grants and HTTP responses; a still-valid token cannot retain access."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, Camera, UserCameraAccess, ApiKey, Transcript):
        model.__table__.create(engine)
    users, cameras, rows = [uuid.uuid4() for _ in range(2)], [uuid.uuid4() for _ in range(2)], []
    now = datetime.now(timezone.utc)
    plaintext, hashed, prefix = auth.generate_api_key()
    with Session(engine) as session:
        for i in range(2):
            session.add(User(id=users[i], email=f"viewer{i}@example.test", password_hash="unused", role="viewer", camera_access_mode="selected"))
            session.add(Camera(id=cameras[i], name=f"Camera {i}", stream_url="test"))
            session.add(UserCameraAccess(user_id=users[i], camera_id=cameras[i]))
            ident = uuid.uuid4()
            rows.append(ident)
            session.add(Transcript(id=ident, camera_id=cameras[i], started_at=now, ended_at=now,
                                   text=f"Private transcript {i}", provider="test", model="test"))
        session.add(ApiKey(user_id=users[0], name="test", key_hash=hashed, prefix=prefix))
        session.commit()

    class Adapter:
        def __init__(self, session):
            self.session = session

        async def execute(self, stmt):
            return self.session.execute(stmt)

        async def get(self, model, ident):
            return self.session.get(model, ident)

        async def commit(self):
            self.session.commit()

    async def session_dependency():
        with Session(engine) as session:
            yield Adapter(session)

    app = FastAPI()
    app.include_router(transcripts.router, prefix="/transcripts")
    app.dependency_overrides[get_db] = session_dependency
    tokens = [auth.create_access_token(user_id) for user_id in users]
    try:
        with TestClient(app) as client:
            for i in range(2):
                headers = {"Authorization": f"Bearer {tokens[i]}"}
                response = client.get("/transcripts?limit=1", headers=headers)
                assert response.status_code == 200
                assert [r["id"] for r in response.json()] == [str(rows[i])]
                assert client.get(f"/transcripts/{rows[1-i]}", headers=headers).status_code == 404
                assert client.get(f"/transcripts/{rows[i]}", headers=headers).status_code == 200
            key_headers = {"Authorization": f"Bearer {plaintext}"}
            assert [r["id"] for r in client.get("/transcripts", headers=key_headers).json()] == [str(rows[0])]
            with Session(engine) as session:
                session.query(UserCameraAccess).filter_by(user_id=users[0]).delete()
                # SQLite drops timezone data; reset the optional write throttle
                # so the next request follows the same first-use path.
                session.query(ApiKey).update({"last_used_at": None})
                session.commit()
            assert client.get("/transcripts", headers=key_headers).json() == []
            old_jwt = {"Authorization": f"Bearer {tokens[0]}"}
            assert client.get(f"/transcripts/{rows[0]}", headers=old_jwt).status_code == 404
    finally:
        engine.dispose()
