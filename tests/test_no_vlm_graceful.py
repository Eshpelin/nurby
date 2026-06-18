"""Graceful degradation when no VLM/LLM provider is configured.

A user with no provider keeps every non-VLM feature working. The
re-interpret endpoints for journeys and incidents must NOT 500 when
there is no provider: they return HTTP 200 with the row's existing
stats plus ``ai_synthesis: false`` and a calm "add a provider" message.

The scheduled-report runner must likewise succeed with a stats-only
digest rather than reporting failure.

Route handlers are invoked directly with stubbed dependencies, matching
the unit-style approach in ``test_agent_routes.py``. No real DB/network.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.api.routes import incidents as incident_routes
from services.api.routes import journeys as journey_routes
from services.perception.incident_tracker import IncidentFinalizer
from services.perception.journey_tracker import JourneyFinalizer


def _run(coro):
    return asyncio.run(coro)


def _now():
    return datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


def _db_get(row):
    """AsyncSession stub whose ``get`` always returns ``row``."""
    db = AsyncMock()

    async def _get(model, key):
        return row

    db.get.side_effect = _get
    return db


def _journey_row():
    return SimpleNamespace(
        id=uuid.uuid4(),
        subject_kind="person",
        subject_key="Simon",
        started_at=_now(),
        last_seen_at=_now(),
        ended_at=None,
        finalized=True,
        segments=[{"camera_name": "Porch", "started_at": _now().isoformat()}],
        transitions=[],
        cameras_seen_count=2,
        incidents_count=3,
        summary_text=None,
        summary_provider_name=None,
        created_at=_now(),
    )


def _incident_row():
    return SimpleNamespace(
        id=uuid.uuid4(),
        camera_id=uuid.uuid4(),
        signature_kind="person",
        signature_key="cluster-9",
        started_at=_now(),
        last_seen_at=_now(),
        ended_at=None,
        finalized=True,
        occurrence_count=4,
        peak_observation_id=None,
        observation_ids=[str(uuid.uuid4())],
        thumbnails=["/t/1.jpg"],
        summary_text=None,
        summary_provider_name=None,
        conversation_id=None,
        created_at=_now(),
    )


# ── journeys: no provider → graceful 200, not 500 ───────────────────


def test_journey_reinterpret_no_provider_returns_graceful_payload(monkeypatch):
    row = _journey_row()
    db = _db_get(row)

    async def _no_provider(self):
        return None

    monkeypatch.setattr(JourneyFinalizer, "_resolve_provider", _no_provider)

    out = _run(
        journey_routes.reinterpret_journey(
            journey_id=row.id, body=None, _user=SimpleNamespace(), db=db
        )
    )
    assert out["ai_synthesis"] is False
    assert "provider" in out["message"].lower()
    # Stats the UI still shows without AI.
    assert out["cameras_seen_count"] == 2
    assert out["incidents_count"] == 3
    assert out["id"] == str(row.id)


def test_journey_reinterpret_missing_journey_still_404(monkeypatch):
    db = _db_get(None)
    with pytest.raises(Exception) as exc:
        _run(
            journey_routes.reinterpret_journey(
                journey_id=uuid.uuid4(), body=None, _user=SimpleNamespace(), db=db
            )
        )
    assert "404" in str(exc.value) or "not found" in str(exc.value)


# ── incidents: no provider → graceful 200, not 500 ──────────────────


def test_incident_reinterpret_no_provider_returns_graceful_payload(monkeypatch):
    row = _incident_row()
    cam = SimpleNamespace(id=row.camera_id, name="Porch")

    # get(Incident, id) → row; get(Camera, id) → cam. Route resolves both.
    db = AsyncMock()

    async def _get(model, key):
        if key == row.id:
            return row
        if key == row.camera_id:
            return cam
        return row

    db.get.side_effect = _get

    # The route loads observations via db.execute before resolving a
    # provider; feed it one obs row so it gets past the empty-guard.
    obs = SimpleNamespace(id=uuid.UUID(row.observation_ids[0]))

    async def _execute(stmt):
        scalar_result = MagicMock()
        scalar_result.all.return_value = [obs]
        result = MagicMock()
        result.scalars.return_value = scalar_result
        return result

    db.execute = _execute

    async def _no_provider(self, cam):
        return None

    monkeypatch.setattr(IncidentFinalizer, "_resolve_provider", _no_provider)

    out = _run(
        incident_routes.reinterpret_incident(
            incident_id=row.id, body=None, _user=SimpleNamespace(), db=db
        )
    )
    assert out["ai_synthesis"] is False
    assert "provider" in out["message"].lower()
    assert out["occurrence_count"] == 4
    assert out["id"] == str(row.id)


def test_incident_reinterpret_missing_incident_still_404(monkeypatch):
    db = _db_get(None)
    with pytest.raises(Exception) as exc:
        _run(
            incident_routes.reinterpret_incident(
                incident_id=uuid.uuid4(), body=None, _user=SimpleNamespace(), db=db
            )
        )
    assert "404" in str(exc.value) or "not found" in str(exc.value)


# ── report scheduler: no provider → stats-only success ──────────────


def test_run_report_no_provider_falls_back_to_stats_digest(monkeypatch):
    from services.api import report_scheduler as rs

    report_id = uuid.uuid4()
    report = SimpleNamespace(
        id=report_id,
        provider_id=None,
        created_by_user_id=uuid.uuid4(),
        person_id=None,
        prompt="What happened today?",
        name="Daily",
    )
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin", is_active=True)

    class _FakeSession:
        async def __aenter__(self):
            db = AsyncMock()

            async def _get(model, key):
                # Report lookup returns the report; user lookup returns admin.
                if key == report_id:
                    return report
                return admin

            db.get.side_effect = _get

            async def _execute(stmt):
                scalar_result = MagicMock()
                scalar_result.all.return_value = [admin]
                scalar_result.first.return_value = admin
                result = MagicMock()
                result.scalars.return_value = scalar_result
                return result

            db.execute = _execute
            return db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(rs, "async_session", lambda: _FakeSession())

    async def _get_setting(key, default=None):
        return None  # no agent_default_provider_id

    monkeypatch.setattr(rs, "get_setting", _get_setting)

    # Stub the digest generator so we exercise the routing, not the DB query.
    async def _fake_digest(db, period="daily", provider=None, **kw):
        assert provider is None  # stats-only path
        return {"summary": "Quiet day. Simon seen around 9:00 am.", "stats": {}}

    import services.search.digest as digest_mod

    monkeypatch.setattr(digest_mod, "generate_digest", _fake_digest)

    status, output = _run(rs.run_report(report_id))
    assert status == "ok"
    assert output and "Simon" in output


def test_run_stats_only_report_empty_digest_returns_empty(monkeypatch):
    from services.api import report_scheduler as rs

    report_id = uuid.uuid4()
    report = SimpleNamespace(id=report_id)

    class _FakeSession:
        async def __aenter__(self):
            db = AsyncMock()

            async def _get(model, key):
                return report

            db.get.side_effect = _get
            return db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(rs, "async_session", lambda: _FakeSession())

    async def _fake_digest(db, period="daily", provider=None, **kw):
        return {"summary": "", "stats": {}}

    import services.search.digest as digest_mod

    monkeypatch.setattr(digest_mod, "generate_digest", _fake_digest)

    status, output = _run(rs.run_stats_only_report(report_id))
    assert status == "empty"
    assert output is None
