"""Auth-gating tests for the privacy-zone write endpoints.

PATCH/DELETE /api/privacy-zones/{id} toggle, unlock, or delete a camera
privacy mask. These are config-level controls and must require admin.
They were admin-gated in #46 (PR #78), silently downgraded back to
get_current_user by a later batch commit, and re-gated here. This test
locks the contract so the regression cannot recur unnoticed:

1. The route's wired dependency tree must include ``require_admin``
   (catches a downgrade to ``get_current_user`` at the decorator site).
2. ``require_admin`` itself must 403 a non-admin (the runtime contract
   FastAPI invokes).

Both checks are DB-free.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from services.api.routes import privacy_zones as pz_routes
from shared.auth import require_admin


class _FakeUser:
    def __init__(self, role: str = "admin") -> None:
        self.id = uuid.uuid4()
        self.role = role
        self.is_active = True


def _run(coro):
    return asyncio.run(coro)


def _direct_dependencies(endpoint_name: str) -> set[str]:
    """Return the callable names of a route's *direct* dependencies (the
    ``Depends(...)`` declared on the handler signature itself).

    We deliberately do NOT recurse: ``require_admin`` itself depends on
    ``get_current_user``, so a recursive walk would always surface
    ``get_current_user`` and mask a downgrade. The handler's direct
    auth dependency is exactly what flipped in the regression, so that
    is what we assert on."""
    for route in pz_routes.router.routes:
        if getattr(route, "name", None) != endpoint_name:
            continue
        return {
            getattr(dep.call, "__name__", str(dep.call))
            for dep in route.dependant.dependencies
            if dep.call is not None
        }
    raise AssertionError(f"route {endpoint_name!r} not found")


@pytest.mark.parametrize("endpoint", ["patch_zone", "delete_zone"])
def test_zone_write_requires_admin_dependency(endpoint):
    """The mutating zone routes must depend directly on ``require_admin``
    and must NOT be gated only by ``get_current_user``."""
    deps = _direct_dependencies(endpoint)
    assert "require_admin" in deps, (
        f"{endpoint} is missing require_admin gating (direct deps={sorted(deps)})"
    )
    assert "get_current_user" not in deps, (
        f"{endpoint} is gated by get_current_user instead of require_admin "
        f"(direct deps={sorted(deps)})"
    )


def test_require_admin_rejects_non_admin_with_403():
    """The runtime contract FastAPI invokes for the gated routes."""
    with pytest.raises(HTTPException) as exc:
        _run(require_admin(current_user=_FakeUser("viewer")))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin():
    user = _FakeUser("admin")
    assert _run(require_admin(current_user=user)) is user
