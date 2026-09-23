"""End-to-end 'system alive' beacon for the external dead-man's switch (#211)."""

import asyncio
from types import SimpleNamespace

import pytest

from shared import beacon, component_health, heartbeat


class _DB:
    def __init__(self, ok=True):
        self._ok = ok

    async def execute(self, stmt):
        if not self._ok:
            raise RuntimeError("db down")
        return SimpleNamespace()


def _patch(monkeypatch, *, ingestion, perception, writer):
    async def _is_alive(service):
        return {heartbeat.INGESTION: ingestion, heartbeat.PERCEPTION: perception}[service]

    async def _get(component):
        return {"status": writer} if writer is not None else None

    monkeypatch.setattr(heartbeat, "is_alive", _is_alive)
    monkeypatch.setattr(component_health, "get", _get)


def _run(monkeypatch, *, db_ok=True, ingestion=True, perception=True, writer=component_health.OK):
    _patch(monkeypatch, ingestion=ingestion, perception=perception, writer=writer)
    return asyncio.run(beacon.compute_beacon(_DB(ok=db_ok)))


def test_all_alive_is_healthy(monkeypatch):
    payload, healthy = _run(monkeypatch)
    assert healthy is True
    assert payload["beacon"] == "alive"
    assert payload["failing"] == []
    assert payload["stale_after_seconds"] == heartbeat.TTL_SECONDS


def test_dead_perception_trips_even_when_api_up(monkeypatch):
    payload, healthy = _run(monkeypatch, perception=False)
    assert healthy is False
    assert payload["beacon"] == "degraded"
    assert "perception" in payload["failing"]
    assert payload["checks"]["database"] is True  # partial degradation


def test_dead_ingestion_is_degraded(monkeypatch):
    _, healthy = _run(monkeypatch, ingestion=False)
    assert healthy is False


def test_db_down_is_degraded(monkeypatch):
    payload, healthy = _run(monkeypatch, db_ok=False)
    assert healthy is False
    assert "database" in payload["failing"]


def test_writer_fail_is_degraded(monkeypatch):
    payload, healthy = _run(monkeypatch, writer=component_health.FAIL)
    assert healthy is False
    assert "observation_writer" in payload["failing"]


def test_writer_unknown_fails_closed(monkeypatch):
    # No writer health published (None) reads as not-confirmed-ok -> degraded.
    payload, healthy = _run(monkeypatch, writer=None)
    assert healthy is False
    assert "observation_writer" in payload["failing"]


# ── HTTP route: status code must reflect health so curl -f trips ──


class _FakeSession:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, *a):
        return False


@pytest.mark.parametrize("healthy,code", [(True, 200), (False, 503)])
def test_beacon_route_status_code_matches_health(monkeypatch, healthy, code):
    from fastapi.testclient import TestClient

    import shared.beacon as beacon_mod
    import shared.database as db_mod
    from services.api.main import app

    async def _compute(db):
        return {"beacon": "alive" if healthy else "degraded", "healthy": healthy, "failing": []}, healthy

    monkeypatch.setattr(beacon_mod, "compute_beacon", _compute)
    monkeypatch.setattr(db_mod, "async_session", lambda: _FakeSession())

    client = TestClient(app)
    resp = client.get("/api/beacon")
    assert resp.status_code == code
    assert resp.json()["healthy"] is healthy


def test_beacon_route_fails_closed_on_exception(monkeypatch):
    from fastapi.testclient import TestClient

    import shared.database as db_mod
    from services.api.main import app

    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(db_mod, "async_session", _boom)
    client = TestClient(app)
    resp = client.get("/api/beacon")
    assert resp.status_code == 503
    assert resp.json()["healthy"] is False
