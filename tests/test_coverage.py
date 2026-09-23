"""Monitoring coverage contract (#194).

Drives compute_coverage with a dispatching mock DB so we can assert the
core promise: a gap (outage or broken pipeline) is never classified as a
quiet period, quiet is distinguished from active, and everything stays
permission-scoped.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.perception import coverage as cov
from shared import component_health, heartbeat
from shared.camera_access import ALL

NOW = datetime.now(timezone.utc)
WINDOW_FROM = NOW - timedelta(hours=24)


class _Res:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows

    def scalars(self):
        return self

    # scalars().all()
    def __iter__(self):
        return iter(self._rows)


class _CovDB:
    """Answers each query compute_coverage issues by inspecting the SQL text.

    Camera rows: (id, name, status, recording_mode).
    obs/caption/recording: (camera_id, max_ts).
    status logs: CameraStatusLog-like objects via scalars().all().
    """

    def __init__(self, *, cameras, last_obs=None, last_caption=None,
                 last_rec=None, status_rows=None):
        self.cameras = cameras
        self.last_obs = last_obs or []
        self.last_caption = last_caption or []
        self.last_rec = last_rec or []
        self.status_rows = status_rows or []

    async def execute(self, stmt):
        t = str(stmt).lower()
        if "from camera_status_logs" in t:
            return _Res(self.status_rows)
        if "from cameras" in t:
            return _Res(self.cameras)
        if "from recordings" in t:
            return _Res(self.last_rec)
        if "vlm_description is not null" in t:
            return _Res(self.last_caption)
        if "from observations" in t:
            return _Res(self.last_obs)
        return _Res([])


@pytest.fixture
def healthy_pipeline(monkeypatch):
    async def _alive(_s):
        return True

    async def _ok(_c):
        return {"status": component_health.OK}

    monkeypatch.setattr(heartbeat, "is_alive", _alive)
    monkeypatch.setattr(component_health, "get", _ok)


def _cam(name="Porch", status="live", mode="always"):
    return (uuid.uuid4(), name, status, mode)


async def _run(db):
    return await cov.compute_coverage(db, allowed=ALL, window_from=WINDOW_FROM, window_to=NOW)


@pytest.mark.asyncio
async def test_active_when_observations_present(healthy_pipeline):
    cid, *_ = cam = _cam()
    db = _CovDB(cameras=[cam], last_obs=[(cid, NOW - timedelta(minutes=5))],
                last_rec=[(cid, NOW - timedelta(minutes=5))])
    rep = await _run(db)
    c = rep["cameras"][0]
    assert c["evidence_state"] == "active"
    assert c["gaps"] == []
    assert rep["summary"]["fully_covered"] is True


@pytest.mark.asyncio
async def test_quiet_when_online_healthy_but_no_events(healthy_pipeline):
    cam = _cam(mode="on_motion")  # no always-on recording expectation
    db = _CovDB(cameras=[cam])
    rep = await _run(db)
    assert rep["cameras"][0]["evidence_state"] == "quiet"
    assert rep["cameras"][0]["gaps"] == []


@pytest.mark.asyncio
async def test_offline_camera_is_outage_not_quiet(healthy_pipeline):
    cam = _cam(status="offline")
    db = _CovDB(cameras=[cam])
    rep = await _run(db)
    c = rep["cameras"][0]
    assert c["evidence_state"] == "outage"
    assert any("offline" in g.lower() for g in c["gaps"])
    assert rep["summary"]["any_outage"] is True
    assert rep["summary"]["fully_covered"] is False


@pytest.mark.asyncio
async def test_outage_interval_from_status_log(healthy_pipeline):
    cid, name, _, mode = _cam()
    cam = (cid, name, "live", mode)  # currently back online
    logs = [
        SimpleNamespace(camera_id=cid, status="offline", reason="stream lost",
                        timestamp=NOW - timedelta(hours=3)),
        SimpleNamespace(camera_id=cid, status="live", reason="reconnected",
                        timestamp=NOW - timedelta(hours=2)),
    ]
    db = _CovDB(cameras=[cam], last_obs=[(cid, NOW - timedelta(minutes=1))], status_rows=logs)
    rep = await _run(db)
    c = rep["cameras"][0]
    # Had an offline interval during the window -> outage overrides "active".
    assert c["evidence_state"] == "outage"
    assert len(c["outages"]) == 1
    assert c["outages"][0]["to"] is not None


@pytest.mark.asyncio
async def test_still_offline_interval_is_open(healthy_pipeline):
    cid, name, _, mode = _cam()
    cam = (cid, name, "offline", mode)
    logs = [SimpleNamespace(camera_id=cid, status="offline", reason="power",
                            timestamp=NOW - timedelta(hours=1))]
    db = _CovDB(cameras=[cam], status_rows=logs)
    rep = await _run(db)
    assert rep["cameras"][0]["outages"][0]["to"] is None


@pytest.mark.asyncio
async def test_broken_pipeline_is_unprocessed_not_quiet(monkeypatch):
    async def _alive(_s):
        return True

    async def _vlm_fail(component):
        if component == component_health.VLM:
            return {"status": component_health.FAIL}
        return {"status": component_health.OK}

    monkeypatch.setattr(heartbeat, "is_alive", _alive)
    monkeypatch.setattr(component_health, "get", _vlm_fail)

    cam = _cam(mode="on_motion")
    db = _CovDB(cameras=[cam])
    rep = await _run(db)
    c = rep["cameras"][0]
    assert c["evidence_state"] == "unprocessed"
    assert any("ai analysis" in g.lower() for g in c["gaps"])


@pytest.mark.asyncio
async def test_always_recording_gap_flagged(healthy_pipeline):
    cid, *_ = cam = _cam(mode="always")
    # online, has observations, but no recording landed in the window
    db = _CovDB(cameras=[cam], last_obs=[(cid, NOW - timedelta(minutes=2))], last_rec=[])
    rep = await _run(db)
    assert any("recording" in g.lower() for g in rep["cameras"][0]["gaps"])


@pytest.mark.asyncio
async def test_coverage_sentences_flatten(healthy_pipeline):
    cam = _cam(status="offline")
    db = _CovDB(cameras=[cam])
    rep = await _run(db)
    lines = cov.coverage_sentences(rep)
    assert lines and rep["cameras"][0]["camera_name"] in lines[0]


# ── route ──

def test_coverage_route_requires_auth():
    from fastapi.testclient import TestClient

    from services.api.main import app

    client = TestClient(app)  # no lifespan
    assert client.get("/api/coverage").status_code == 401


def test_coverage_route_returns_report(healthy_pipeline):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from services.api.routes import coverage as route
    from shared.auth import get_current_user
    from shared.database import get_db

    cid, name, status, mode = _cam(status="offline")
    db = _CovDB(cameras=[(cid, name, status, mode)])

    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), role="admin", is_active=True
    )

    client = TestClient(app)
    resp = client.get("/api/coverage?hours=12")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["any_outage"] is True
    assert body["cameras"][0]["evidence_state"] == "outage"
