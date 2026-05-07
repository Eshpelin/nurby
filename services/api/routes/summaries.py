"""Read-only summaries API.

The summarizer worker writes rows. The frontend reads them via this
router. Filters mirror the timeline route. ``camera_id`` and a
date-range window are the only meaningful pivots for now.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.database import get_db
from shared.models import Summary, User

router = APIRouter()


def _serialize(s: Summary) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "camera_id": str(s.camera_id),
        "kind": s.kind,
        "started_at": s.started_at.isoformat(),
        "ended_at": s.ended_at.isoformat(),
        "provider_name": s.provider_name,
        "trigger_reason": s.trigger_reason,
        "summary_text": s.summary_text,
        "people_seen": s.people_seen,
        "plates_seen": s.plates_seen,
        "object_counts": s.object_counts,
        "source_observation_ids": s.source_observation_ids,
        "source_transcript_ids": s.source_transcript_ids,
        "created_at": s.created_at.isoformat(),
    }


@router.get("")
async def list_summaries(
    camera_id: uuid.UUID | None = Query(default=None),
    kind: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Summary).order_by(Summary.started_at.desc())
    if camera_id:
        q = q.where(Summary.camera_id == camera_id)
    if kind:
        q = q.where(Summary.kind == kind)
    if from_:
        q = q.where(Summary.started_at >= from_)
    if to:
        q = q.where(Summary.started_at <= to)
    rows = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/{summary_id}")
async def get_summary(
    summary_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Summary, summary_id)
    if row is None:
        raise HTTPException(status_code=404, detail="summary not found")
    return _serialize(row)
