"""Rate limiting on /auth/login and /auth/bootstrap/adopt (#328).

Follows the DB-free, unit-style convention of tests/test_auth_onboarding.py:
handlers are invoked directly with a stubbed AsyncSession and hand-built
starlette Requests. The remote-access ingress puts these endpoints on the
public internet, so this is the brute-force gate.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from services.api.routes import auth as auth_routes
from shared.auth import hash_password
from shared.models import User
from shared.rate_limit import SlidingWindowLimiter
from shared.schemas import SetupCodeAdoption, UserLogin


def _req(ip: str = "203.0.113.9") -> Request:
    return Request({
        "type": "http", "headers": [], "scheme": "http",
        "server": ("localhost", 4848), "client": (ip, 5150),
    })


def _login_db(user: User | None):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _user(password: str = "correct-horse") -> User:
    return User(
        email="user@example.com",
        display_name="User",
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def _adopt_db(owner: User):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [owner]
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _run(coro):
    return asyncio.run(coro)


def _attempt_login(password: str, db) -> None:
    _run(auth_routes.login(
        UserLogin(email="user@example.com", password=password), _req(), db=db,
    ))


@pytest.fixture(autouse=True)
def _clean_limiters():
    auth_routes._email_limiter.clear()
    auth_routes._ip_limiter.clear()
    yield
    auth_routes._email_limiter.clear()
    auth_routes._ip_limiter.clear()


def test_sixth_failed_login_is_rejected_with_retry_after():
    db = _login_db(_user())
    for _ in range(auth_routes.settings.login_rate_limit_attempts):
        with pytest.raises(HTTPException) as exc:
            _attempt_login("wrong", db)
        assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        _attempt_login("wrong", db)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_correct_password_resets_the_email_bucket():
    db = _login_db(_user())
    for _ in range(auth_routes.settings.login_rate_limit_attempts - 1):
        with pytest.raises(HTTPException):
            _attempt_login("wrong", db)
    _attempt_login("correct-horse", db)  # success clears the bucket
    with pytest.raises(HTTPException) as exc:
        _attempt_login("wrong", db)  # one fresh failure: allowed, not 429
    assert exc.value.status_code == 401


def test_rate_limit_is_per_email_not_global():
    db = _login_db(_user())
    for _ in range(auth_routes.settings.login_rate_limit_attempts):
        with pytest.raises(HTTPException):
            _attempt_login("wrong", db)
    # A different account from the same source is only counted against
    # the (much looser) source bucket.
    other = User(
        email="other@example.com", display_name="O",
        password_hash=hash_password("pw2"), role="viewer", is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db2 = _login_db(other)
    _run(auth_routes.login(
        UserLogin(email="other@example.com", password="pw2"), _req(), db=db2,
    ))


def test_adopt_invalid_code_records_source_failure():
    owner = _user()
    owner.is_provisional = True
    owner.setup_code_hash = "A" * 64
    db = _adopt_db(owner)
    ip_cap = auth_routes.settings.login_rate_limit_ip_attempts
    for _ in range(ip_cap):
        with pytest.raises(HTTPException) as exc:
            _run(auth_routes.adopt_provisional_owner(
                SetupCodeAdoption(code="DEADBEEF"), request=_req(), response=None, db=db,
            ))
        assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        _run(auth_routes.adopt_provisional_owner(
            SetupCodeAdoption(code="DEADBEEF"), request=_req(), response=None, db=db,
        ))
    assert exc.value.status_code == 429


def test_limiter_window_slides():
    limiter = SlidingWindowLimiter(max_attempts=2, window_s=100.0)
    clock = {"now": 0.0}
    limiter._clock = lambda: clock["now"]
    limiter.record_failure("k")
    limiter.record_failure("k")
    assert limiter.retry_after_s("k") > 0
    clock["now"] = 100.1  # both failures aged out of the window
    assert limiter.retry_after_s("k") == 0.0
    limiter.record_success("k")
    assert limiter.retry_after_s("k") == 0.0
