"""Daily household digest API.

GET /api/daily-digest             latest digest (or null if none)
GET /api/daily-digest/history     last N digests
POST /api/daily-digest/run        force-generate on demand
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import ALL, allowed_camera_ids
from shared.database import get_db
from shared.models import DailyDigest, User

router = APIRouter()


def _serialize(d: DailyDigest) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "window_start": d.window_start.isoformat(),
        "window_end": d.window_end.isoformat(),
        "generated_at": d.generated_at.isoformat(),
        "provider_name": d.provider_name,
        "summary_text": d.summary_text,
        "facts": d.facts,
    }


async def _scoped_digest(camera_ids: set) -> dict[str, Any]:
    """Build a fresh, unpersisted, facts-only digest restricted to
    ``camera_ids``. The persisted DailyDigest rows are household-wide
    (see services/perception/daily_digest.py), so a camera-restricted
    viewer can't be served one of those without leaking other
    cameras' activity — this computes their own scoped view on
    request instead, skipping the VLM narrative for speed."""
    from services.perception.daily_digest import _collect_facts

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    facts = await _collect_facts(start, end, camera_ids=camera_ids)
    return {
        "id": None,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "generated_at": end.isoformat(),
        "provider_name": None,
        "summary_text": None,
        "facts": facts,
    }


@router.get("")
async def latest_digest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL:
        return await _scoped_digest(allowed)
    row = (
        await db.execute(
            select(DailyDigest).order_by(DailyDigest.generated_at.desc()).limit(1)
        )
    ).scalars().first()
    return _serialize(row) if row else None


@router.get("/history")
async def history(
    limit: int = Query(default=14, ge=1, le=120),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL:
        # Household history is a running narrative across every camera;
        # there's no per-day scoped equivalent to hand back, so a
        # restricted viewer gets today's scoped snapshot as the only
        # entry instead of other households' history.
        return [await _scoped_digest(allowed)]
    rows = (
        await db.execute(
            select(DailyDigest)
            .order_by(DailyDigest.generated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("/run")
async def run_now(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force-generate a digest now for the last 24h. Returns the
    new row. Skipped when the daily worker has produced one in the
    last 23h — admin tool only."""
    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL:
        return await _scoped_digest(allowed)

    from services.perception.daily_digest import build_daily_digest

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    row = await build_daily_digest(window_start=start, window_end=end)
    if row is None:
        raise HTTPException(status_code=500, detail="digest generation failed")
    return _serialize(row)
