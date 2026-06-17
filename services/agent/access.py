"""User access filter for agent tools.

Every agent tool funnels its result set through ``accessible_camera_ids``
before returning rows. The actual policy lives in the central
``shared.camera_access.allowed_camera_ids`` helper (issue #40) so the
agent surface, the REST list endpoints, and the future WS fan-out all
share one source of truth. This wrapper materializes the central
``ALL`` sentinel into the concrete ``set[UUID]`` the agent tools expect,
keeping their existing contract unchanged.

Admin users see every camera. Regular users see the cameras shared with
them via the ``UserCameraAccess`` table; a regular user with zero rows in
that table falls through to the full camera list, matching the read
endpoints which do not gate at the row level until an admin opts the user
into an allowlist.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.camera_access import ALL, allowed_camera_ids
from shared.models import Camera, User


async def accessible_camera_ids(user: User, db: AsyncSession) -> set[uuid.UUID]:
    """Return the set of camera UUIDs this user is allowed to query.

    Thin adapter over :func:`shared.camera_access.allowed_camera_ids`. The
    central helper returns ``ALL`` for unrestricted users (admins, or
    regular users with no explicit grants); the agent tools want a
    concrete set, so ``ALL`` is expanded to the full camera-id set here.
    A restricted user's allowlist is intersected with the live camera set
    so stale grants for deleted cameras never leak.
    """
    allowed = await allowed_camera_ids(user, db)
    all_camera_ids = {
        row[0]
        for row in (await db.execute(select(Camera.id))).all()
    }
    if allowed is ALL:
        return all_camera_ids
    return allowed & all_camera_ids
