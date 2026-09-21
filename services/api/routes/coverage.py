"""Monitoring coverage endpoint (#194).

Serves the permission-scoped coverage report that Home banners, recaps and
Ask answers use to qualify their conclusions: which cameras were watchable,
when they were offline, and whether an absence of events was a real quiet
period or a coverage gap. Reads the same liveness sources as the doctor and
the beacon; never exposes a camera outside the viewer's allowlist.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.coverage import compute_coverage
from shared.auth import get_current_user
from shared.camera_access import allowed_camera_ids
from shared.database import get_db
from shared.models import User

router = APIRouter()


@router.get("/coverage")
async def get_coverage(
    hours: int = Query(default=24, ge=1, le=720, description="Window size in hours"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Coverage report over the last ``hours`` for the viewer's cameras."""
    allowed = await allowed_camera_ids(_user, db)
    window_to = datetime.now(timezone.utc)
    window_from = window_to - timedelta(hours=hours)
    return await compute_coverage(
        db, allowed=allowed, window_from=window_from, window_to=window_to
    )
