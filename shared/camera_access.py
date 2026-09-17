"""Central per-user camera access-control (ACL) helper.

One source of truth for "which cameras may this user see". Every read
surface that returns camera-scoped rows (list endpoints, agent tools, and
eventually the WS fan-out + media-serving endpoints) funnels through
``allowed_camera_ids`` so the policy lives in exactly one place. This
mirrors Guardian's already-scoped ``_allowed_cameras`` posture on the main
app surface (see issue #40 and
``docs/frigate-study/initiatives/camera-access-control.md``).

Policy (explicit access, issue #190):

* **Admins** see every camera. Returns the :data:`ALL` sentinel.
* Non-admins in **all** mode explicitly see every camera.
* **selected** mode returns the explicit grants, including an empty set.
* **none**, missing, or unknown modes fail closed. New accounts default to none.
  Existing access is preserved explicitly by the migration, never inferred
  from an empty grant list at request time.

The ``ALL`` sentinel is preferred over materializing the full camera-id
set: it lets callers skip the ``WHERE ... IN (...)`` clause entirely (no
giant id list, no extra query) when the user is unrestricted, while still
giving a precise ``set`` to filter on when they are restricted.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import Select

from shared.models import User, UserCameraAccess


class _All:
    """Singleton sentinel meaning 'every camera, no filter'.

    Distinct from an empty ``set`` (which means 'no cameras at all'). Kept
    as a dedicated type so ``allowed is ALL`` reads clearly at call sites
    and a stray empty set is never silently treated as unrestricted.
    """

    _instance: "_All | None" = None

    def __new__(cls) -> "_All":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "ALL"

    def __bool__(self) -> bool:
        # Truthy so ``if allowed:`` does not accidentally read ALL as "no
        # access". Callers should test ``allowed is ALL`` explicitly, but
        # this keeps the obvious truthiness intuitive.
        return True


ALL: Final[_All] = _All()

AllowedCameras = _All | set[uuid.UUID]


async def allowed_camera_ids(user: User, db: AsyncSession) -> AllowedCameras:
    """Return the cameras ``user`` may see: :data:`ALL` or a ``set`` of ids.

    See the module docstring for the policy. ``ALL`` means "no filter,
    every camera"; a ``set`` (possibly empty) is an explicit allowlist.
    """
    role = getattr(user, "role", None)
    if role == "admin":
        return ALL

    mode = getattr(user, "camera_access_mode", "none")
    if mode == "all":
        return ALL
    if mode != "selected":
        return set()

    rows = (
        await db.execute(
            select(UserCameraAccess.camera_id).where(
                UserCameraAccess.user_id == user.id
            )
        )
    ).all()
    return {row[0] for row in rows}


def apply_camera_filter(
    query: Select,
    allowed: AllowedCameras,
    column: ColumnElement,
) -> Select:
    """Narrow ``query`` to ``allowed`` cameras using ``column``.

    No-op when ``allowed is ALL``. When ``allowed`` is an empty set the
    query is forced to return nothing (the user has an allowlist but it is
    empty), which is the safe, fail-closed result.
    """
    if allowed is ALL:
        return query
    return query.where(column.in_(allowed))
