"""Tests for GET/PATCH /api/system/settings.

The endpoints touch a real ``AppSetting`` table when run against
Postgres, but the route handlers call ``get_setting`` and
``set_setting`` directly. We monkeypatch both at the call site so the
tests stay DB-free.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from services.api.routes import system as system_routes
from shared.schemas import SystemSettingsUpdate


class _FakeUser:
    def __init__(self, role: str = "admin") -> None:
        self.id = uuid.uuid4()
        self.role = role
        self.is_active = True


@pytest.fixture(autouse=True)
def _in_memory_settings(monkeypatch):
    """Replace get_setting / set_setting with a dict-backed store so
    no Postgres is needed. Returns the store for assertion."""
    store: dict[str, object] = {}

    async def fake_get_setting(key, default=None):
        from shared.app_settings import DEFAULTS
        if key in store:
            return store[key]
        return DEFAULTS.get(key, default)

    async def fake_set_setting(key, value):
        store[key] = value

    monkeypatch.setattr(
        "shared.app_settings.get_setting", fake_get_setting,
    )
    monkeypatch.setattr(
        "shared.app_settings.set_setting", fake_set_setting,
    )
    return store


def _run(coro):
    return asyncio.run(coro)


# ── GET ──────────────────────────────────────────────────────────────

def test_get_returns_whitelist_with_defaults():
    resp = _run(system_routes.get_settings(_current_user=_FakeUser("viewer")))
    data = resp.model_dump()
    assert data["system_timezone"] is None
    assert data["journey_idle_seconds"] == 300
    assert data["daily_digest_enabled"] is True
    assert data["daily_digest_hour"] == 7
    assert data["nudity_blur"] is True
    assert data["audio_events"] is True
    assert data["body_reid_tentative_decay_days"] == 14
    assert data["cluster_naming_min_sightings"] == 3
    # public_base_url falls back to env settings.public_base_url when
    # nothing is stored; either None or a string is acceptable.
    assert "public_base_url" in data


# ── PATCH happy path ─────────────────────────────────────────────────

def test_patch_as_admin_updates_timezone_and_get_reflects(_in_memory_settings):
    body = SystemSettingsUpdate(system_timezone="America/Los_Angeles")
    resp = _run(system_routes.patch_settings(body=body, _current_user=_FakeUser("admin")))
    assert resp.system_timezone == "America/Los_Angeles"

    # Confirm GET also sees it.
    again = _run(system_routes.get_settings(_current_user=_FakeUser("viewer")))
    assert again.system_timezone == "America/Los_Angeles"


# ── PATCH auth gate ──────────────────────────────────────────────────

def test_patch_as_non_admin_is_403():
    """``require_admin`` is the dependency. We exercise it directly to
    prove the contract; FastAPI wires the same call at runtime."""
    from shared.auth import require_admin

    with pytest.raises(HTTPException) as exc:
        _run(require_admin(current_user=_FakeUser("viewer")))
    assert exc.value.status_code == 403


# ── PATCH validation ─────────────────────────────────────────────────

def test_patch_with_invalid_timezone_returns_400():
    body = SystemSettingsUpdate(system_timezone="Not/Real")
    with pytest.raises(HTTPException) as exc:
        _run(system_routes.patch_settings(body=body, _current_user=_FakeUser("admin")))
    assert exc.value.status_code == 400
    assert "timezone" in exc.value.detail.lower()


def test_patch_with_non_whitelisted_key_rejected_by_schema():
    """Pydantic ``extra=forbid`` blocks unknown keys at parse time."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SystemSettingsUpdate(secret_token="leak")  # type: ignore[call-arg]


def test_patch_with_non_whitelisted_key_via_handler_returns_400():
    """Defense in depth. Even if a bad body slips past the schema
    layer, the handler rejects keys outside the whitelist with 400.
    Simulated by feeding the handler a stand-in object whose
    ``model_dump`` returns a stray key.

    This guards against accidental schema additions widening the
    public surface in the future."""

    class _Body:
        def model_dump(self, **_kw):
            return {"secret_token": "leak"}

    with pytest.raises(HTTPException) as exc:
        _run(system_routes.patch_settings(body=_Body(), _current_user=_FakeUser("admin")))  # type: ignore[arg-type]
    assert exc.value.status_code == 400
    assert "unknown" in exc.value.detail.lower()
