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
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from services.api.routes import auth as auth_routes
from services.api.routes import cameras as camera_routes
from shared.schemas import AccountClaim, AdminSetup, SetupCodeAdoption


def _run(coro):
    return asyncio.run(coro)


def _http(cookie: str | None = None):
    headers = [] if cookie is None else [(b"cookie", f"nurby_install_secret={cookie}".encode())]
    return Request({"type": "http", "headers": headers, "scheme": "http", "server": ("localhost", 4848)})


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
        self.bootstrap_secret_hash = None
        self.setup_code_hash = None
        self.setup_code_ciphertext = None


def _exec_result(*, scalar=None, scalar_one_or_none=None, first=None, all=None):
    """Build a stub result object for db.execute() return values."""
    res = MagicMock()
    res.scalar.return_value = scalar
    res.scalar_one_or_none.return_value = scalar_one_or_none
    scalars = MagicMock()
    scalars.first.return_value = first
    scalars.all.return_value = all if all is not None else []
    res.scalars.return_value = scalars
    return res


# ── bootstrap ────────────────────────────────────────────────────────

def test_bootstrap_creates_provisional_owner_on_fresh_install():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    # Two execute() calls. the advisory lock, then the user query (none).
    db.execute.side_effect = [
        _exec_result(),            # pg_advisory_xact_lock
        _exec_result(all=[]),      # no users yet
    ]

    async def _refresh(obj):
        # Postgres would stamp these on insert; mimic for serialization.
        obj.id = uuid.uuid4()
        obj.created_at = datetime.now(timezone.utc)
        obj.last_login_at = None

    db.refresh.side_effect = _refresh

    response = Response()
    token = _run(auth_routes.bootstrap(request=_http(), response=response, db=db))

    assert token.access_token
    assert token.user.role == "admin"
    assert token.user.is_provisional is True
    # A real, unique placeholder email was assigned.
    assert token.user.email.endswith("@nurby.local")
    assert "nurby_install_secret=" in response.headers["set-cookie"]
    assert token.setup_code and len(token.setup_code) == 8
    db.add.assert_called_once()
    db.commit.assert_awaited()


def test_bootstrap_conflicts_when_a_claimed_user_exists():
    claimed = _FakeUser(provisional=False, email="real@example.com")
    db = AsyncMock()
    db.execute.side_effect = [
        _exec_result(),                 # lock
        _exec_result(all=[claimed]),    # a real account exists
    ]

    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.bootstrap(db=db))
    assert ei.value.status_code == 409


def test_bootstrap_readopts_unclaimed_provisional_owner():
    # A visitor who lost their token re-adopts the existing unclaimed owner
    # instead of being stranded. No new user is created.
    owner = _FakeUser(provisional=True)
    secret = "install-secret"
    owner.bootstrap_secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        _exec_result(),               # lock
        _exec_result(all=[owner]),    # only an unclaimed provisional owner
    ]

    token = _run(auth_routes.bootstrap(request=_http(secret), db=db))
    assert token.user.id == owner.id
    assert token.user.is_provisional is True
    db.add.assert_not_called()


def test_bootstrap_rejects_unbound_browser_for_unclaimed_owner():
    owner = _FakeUser(provisional=True)
    owner.bootstrap_secret_hash = hashlib.sha256(b"install-secret").hexdigest()
    db = AsyncMock()
    db.execute.side_effect = [_exec_result(), _exec_result(all=[owner])]

    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.bootstrap(request=_http(), db=db))
    assert ei.value.status_code == 409


def test_setup_code_adopts_once_and_rebinds_browser():
    owner = _FakeUser(provisional=True)
    code = "A1B2C3D4"
    owner.setup_code_hash = hashlib.sha256(code.encode()).hexdigest()
    owner.setup_code_ciphertext = auth_routes.seal(code)
    db = AsyncMock()
    db.execute.side_effect = [
        _exec_result(),
        _exec_result(all=[owner]),
    ]
    db.commit = AsyncMock()
    response = Response()
    token = _run(auth_routes.adopt_provisional_owner(
        body=SetupCodeAdoption(code=code.lower()),
        response=response,
        db=db,
    ))
    assert token.user.id == owner.id
    assert owner.setup_code_hash is None
    assert owner.setup_code_ciphertext is None
    assert owner.bootstrap_secret_hash
    assert "nurby_install_secret=" in response.headers["set-cookie"]


def test_setup_code_is_single_use():
    owner = _FakeUser(provisional=True)
    owner.setup_code_hash = hashlib.sha256(b"A1B2C3D4").hexdigest()
    db = AsyncMock()
    db.execute.side_effect = [_exec_result(), _exec_result(all=[owner])]
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.adopt_provisional_owner(
            body=SetupCodeAdoption(code="WRONG123"), db=db,
        ))
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


def test_new_demo_camera_is_recording_with_bounded_retention(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute.side_effect = [
        _exec_result(first=None),  # no existing demo camera
        _exec_result(all=[]),      # no display orders yet
    ]
    monkeypatch.setattr(camera_routes, "_camera_to_response", lambda c: c)
    monkeypatch.setattr(
        camera_routes,
        "resolve_demo_video_url",
        lambda: "https://example.test/demo.mp4",
    )

    out = _run(camera_routes.create_demo_camera(_current_user=_FakeUser(), db=db))

    assert out.recording_enabled is True
    assert out.recording_mode == "always"
    assert out.retention_mode == "time"
    assert out.retention_days == 1
