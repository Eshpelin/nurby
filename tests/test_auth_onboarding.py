"""Tests for the first-run onboarding auth paths.

Covers the provisional-owner flow added for frictionless setup:
  - POST /auth/bootstrap auto-creates a provisional admin on a fresh
    install and 409s once any user exists.
  - POST /auth/claim secures the account (real email + password), clears
    the provisional flag, and rejects a duplicate email.
  - Email-shape validation on the credential schemas, which guards a
    lockout bug (a malformed login email no one could ever type).
  - The demo camera endpoint is idempotent.

Handlers are invoked directly with a stubbed AsyncSession, matching the
DB-free, unit-style convention of the rest of the suite.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.api.routes import auth as auth_routes
from services.api.routes import cameras as camera_routes
from shared.schemas import AccountClaim, AdminSetup


def _run(coro):
    return asyncio.run(coro)


class _FakeUser:
    def __init__(self, *, provisional: bool = True, email: str = "owner@nurby.local"):
        self.id = uuid.uuid4()
        self.email = email
        self.display_name = "Owner"
        self.password_hash = "x"
        self.role = "admin"
        self.is_active = True
        self.is_provisional = provisional
        self.created_at = datetime.now(timezone.utc)
        self.last_login_at = None


def _exec_result(*, scalar=None, scalar_one_or_none=None, first=None):
    """Build a stub result object for db.execute() return values."""
    res = MagicMock()
    res.scalar.return_value = scalar
    res.scalar_one_or_none.return_value = scalar_one_or_none
    scalars = MagicMock()
    scalars.first.return_value = first
    res.scalars.return_value = scalars
    return res


# ── bootstrap ────────────────────────────────────────────────────────

def test_bootstrap_creates_provisional_owner_on_fresh_install():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    # Two execute() calls. the advisory lock, then the user count (0).
    db.execute.side_effect = [
        _exec_result(),            # pg_advisory_xact_lock
        _exec_result(scalar=0),    # count == 0
    ]

    async def _refresh(obj):
        # Postgres would stamp these on insert; mimic for serialization.
        obj.id = uuid.uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.last_login_at = None

    db.refresh.side_effect = _refresh

    token = _run(auth_routes.bootstrap(db=db))

    assert token.access_token
    assert token.user.role == "admin"
    assert token.user.is_provisional is True
    # A real, unique placeholder email was assigned.
    assert token.user.email.endswith("@nurby.local")
    db.add.assert_called_once()
    db.commit.assert_awaited()


def test_bootstrap_conflicts_when_a_user_already_exists():
    db = AsyncMock()
    db.execute.side_effect = [
        _exec_result(),            # lock
        _exec_result(scalar=1),    # count > 0
    ]

    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.bootstrap(db=db))
    assert ei.value.status_code == 409


# ── claim ────────────────────────────────────────────────────────────

def test_claim_secures_provisional_account():
    user = _FakeUser(provisional=True)
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    # No other user holds the target email.
    db.execute.return_value = _exec_result(scalar_one_or_none=None)

    body = AccountClaim(email="real@example.com", password="supersecret", display_name="Alex")
    out = _run(auth_routes.claim_account(body=body, current_user=user, db=db))

    assert out.email == "real@example.com"
    assert out.display_name == "Alex"
    assert out.is_provisional is False
    # The password hash was rotated away from the placeholder.
    assert user.password_hash != "x"


def test_claim_rejects_duplicate_email():
    user = _FakeUser(provisional=True)
    other = _FakeUser(provisional=False, email="real@example.com")
    db = AsyncMock()
    db.execute.return_value = _exec_result(scalar_one_or_none=other)

    body = AccountClaim(email="real@example.com", password="supersecret")
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.claim_account(body=body, current_user=user, db=db))
    assert ei.value.status_code == 409
    # The account stays provisional. claiming did not half-apply.
    assert user.is_provisional is True


# ── schema validation (guards the lockout bug) ───────────────────────

@pytest.mark.parametrize("bad", ["notanemail", "a@b", "x y@z.com", "@b.com", "a@.com", "abc"])
def test_account_claim_rejects_malformed_email(bad):
    with pytest.raises(ValueError):
        AccountClaim(email=bad, password="supersecret")


@pytest.mark.parametrize("good", ["a@b.com", "owner.name+tag@sub.example.io"])
def test_account_claim_accepts_valid_email(good):
    assert AccountClaim(email=good, password="supersecret").email == good


def test_admin_setup_rejects_malformed_email():
    with pytest.raises(ValueError):
        AdminSetup(email="nope", password="supersecret")


def test_account_claim_enforces_min_password_length():
    with pytest.raises(ValueError):
        AccountClaim(email="a@b.com", password="short")


# ── demo camera idempotency ──────────────────────────────────────────

def test_demo_camera_reused_when_one_exists(monkeypatch):
    existing = MagicMock()
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = _exec_result(first=existing)

    # Avoid serializing a full Camera. assert we returned the existing one.
    monkeypatch.setattr(camera_routes, "_camera_to_response", lambda c: c)

    out = _run(camera_routes.create_demo_camera(_current_user=_FakeUser(), db=db))

    assert out is existing
    # No new row was inserted.
    db.add.assert_not_called()
