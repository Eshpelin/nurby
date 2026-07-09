"""Tests for the mobile QR pairing flow.

Covers:
  - POST /auth/pair/start mints a purpose-scoped, short-lived code.
  - POST /auth/pair/claim exchanges a valid code for an access token.
  - A code is single-use: the second claim is rejected.
  - Expired, malformed, and wrong-purpose tokens are rejected.
  - Deactivated users cannot claim.

Handlers are invoked directly with a stubbed AsyncSession, matching the
DB-free, unit-style convention of the rest of the suite.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from jose import jwt

from services.api.routes import auth as auth_routes
from shared.auth import (
    ALGORITHM,
    MOBILE_PAIR_TTL_SECONDS,
    create_mobile_pair_code,
    decode_access_token,
    decode_mobile_pair_code,
)
from shared.config import settings
from shared.schemas import PairClaim


def _run(coro):
    return asyncio.run(coro)


class _FakeUser:
    def __init__(self, *, active: bool = True):
        self.id = uuid.uuid4()
        self.email = "owner@example.com"
        self.display_name = "Owner"
        self.password_hash = "x"
        self.role = "admin"
        self.is_active = active
        self.is_provisional = False
        self.created_at = datetime.now(timezone.utc)
        self.last_login_at = None


def _db_returning(user):
    db = AsyncMock()
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _clear_used_jtis():
    auth_routes._used_pair_jtis.clear()
    yield
    auth_routes._used_pair_jtis.clear()


# ── code mint / decode ───────────────────────────────────────────────

def test_pair_code_roundtrip():
    user_id = uuid.uuid4()
    code = create_mobile_pair_code(user_id)
    decoded = decode_mobile_pair_code(code)
    assert decoded is not None
    got_id, jti = decoded
    assert got_id == user_id
    assert jti


def test_pair_code_rejects_wrong_purpose():
    # A normal access token must not work as a pairing code.
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    assert decode_mobile_pair_code(token) is None


def test_pair_code_rejects_expired():
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) - timedelta(seconds=5),
        "purpose": "mobile_pair",
        "jti": "abc",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    assert decode_mobile_pair_code(token) is None


def test_pair_code_rejects_garbage():
    assert decode_mobile_pair_code("not-a-jwt") is None


# ── /pair/start ──────────────────────────────────────────────────────

def test_pair_start_returns_valid_code():
    user = _FakeUser()
    resp = _run(auth_routes.pair_start(current_user=user))
    assert resp.expires_in == MOBILE_PAIR_TTL_SECONDS
    decoded = decode_mobile_pair_code(resp.code)
    assert decoded is not None
    assert decoded[0] == user.id


# ── /pair/claim ──────────────────────────────────────────────────────

def test_pair_claim_returns_access_token():
    user = _FakeUser()
    db = _db_returning(user)
    code = create_mobile_pair_code(user.id)

    resp = _run(auth_routes.pair_claim(PairClaim(code=code), db=db))

    assert decode_access_token(resp.access_token) == user.id
    assert resp.user.email == user.email
    assert user.last_login_at is not None
    db.commit.assert_awaited()


def test_pair_claim_is_single_use():
    user = _FakeUser()
    db = _db_returning(user)
    code = create_mobile_pair_code(user.id)

    _run(auth_routes.pair_claim(PairClaim(code=code), db=db))
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.pair_claim(PairClaim(code=code), db=db))
    assert ei.value.status_code == 401
    assert "already used" in ei.value.detail


def test_pair_claim_rejects_invalid_code():
    db = _db_returning(None)
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.pair_claim(PairClaim(code="bogus"), db=db))
    assert ei.value.status_code == 401


def test_pair_claim_rejects_unknown_user():
    db = _db_returning(None)
    code = create_mobile_pair_code(uuid.uuid4())
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.pair_claim(PairClaim(code=code), db=db))
    assert ei.value.status_code == 401


def test_pair_claim_rejects_deactivated_user():
    user = _FakeUser(active=False)
    db = _db_returning(user)
    code = create_mobile_pair_code(user.id)
    with pytest.raises(HTTPException) as ei:
        _run(auth_routes.pair_claim(PairClaim(code=code), db=db))
    assert ei.value.status_code == 401


def test_used_jti_pruning():
    now = datetime.now(timezone.utc)
    auth_routes._used_pair_jtis["old"] = now - timedelta(seconds=1)
    auth_routes._used_pair_jtis["fresh"] = now + timedelta(seconds=60)
    auth_routes._prune_used_jtis(now)
    assert "old" not in auth_routes._used_pair_jtis
    assert "fresh" in auth_routes._used_pair_jtis
