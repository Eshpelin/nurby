"""Expected-activity expectations API (#215).

CRUD for the scheduled windows the sweeper evaluates. Permission-scoped: a
user may only create/see expectations whose cameras they can all see (an
expectation with no cameras means "any camera", visible to everyone).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import ALL, allowed_camera_ids
from shared.database import get_db
from shared.household_mode import MODES
from shared.models import ExpectedActivity, User

router = APIRouter()

_SUBJECT_KINDS = {"person", "any_person", "any_activity"}
_HHMM = r"^([01]?\d|2[0-3]):[0-5]\d$"


class ExpectedActivityBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subject_kind: str = "person"
    subject_key: str | None = Field(default=None, max_length=255)
    camera_ids: list[uuid.UUID] = Field(default_factory=list)
    weekdays: list[int] = Field(default_factory=list)
    start_time: str = Field(pattern=_HHMM)
    end_time: str = Field(pattern=_HHMM)
    grace_minutes: int = Field(default=30, ge=0, le=1440)
    active_modes: list[str] | None = None
    enabled: bool = True


def _validate(body: ExpectedActivityBody) -> None:
    if body.subject_kind not in _SUBJECT_KINDS:
        raise HTTPException(status_code=422, detail="invalid subject_kind")
    if body.subject_kind == "person" and not (body.subject_key or "").strip():
        raise HTTPException(status_code=422, detail="person expectation needs a subject_key")
    if not body.weekdays or any(d < 0 or d > 6 for d in body.weekdays):
        raise HTTPException(status_code=422, detail="weekdays must be a non-empty list of 0..6")
    if body.active_modes is not None and any(m not in MODES for m in body.active_modes):
        raise HTTPException(status_code=422, detail="active_modes must be a subset of household modes")


async def _require_cameras_in_scope(cams: list[uuid.UUID], user: User, db: AsyncSession) -> None:
    if not cams:
        return  # "any camera" is allowed for anyone
    allowed = await allowed_camera_ids(user, db)
    if allowed is ALL:
        return
    foreign = [c for c in cams if c not in allowed]
    if foreign:
        raise HTTPException(status_code=404, detail="camera not found")


def _serialize(e: ExpectedActivity) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "name": e.name,
        "subject_kind": e.subject_kind,
        "subject_key": e.subject_key,
        "camera_ids": [str(c) for c in (e.camera_ids or [])],
        "weekdays": e.weekdays or [],
        "start_time": e.start_time,
        "end_time": e.end_time,
        "grace_minutes": e.grace_minutes,
        "active_modes": e.active_modes,
        "enabled": e.enabled,
        "last_evaluated_on": e.last_evaluated_on,
        "last_status": e.last_status,
    }


def _visible(e: ExpectedActivity, allowed) -> bool:
    if allowed is ALL:
        return True
    cams = {str(c) for c in (e.camera_ids or [])}
    if not cams:
        return True
    return cams.issubset({str(c) for c in allowed})


@router.get("")
async def list_expected(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Expectations the caller may see, with each one's last outcome (recap)."""
    allowed = await allowed_camera_ids(user, db)
    rows = (
        await db.execute(select(ExpectedActivity).order_by(ExpectedActivity.created_at.desc()))
    ).scalars().all()
    return [_serialize(e) for e in rows if _visible(e, allowed)]


@router.post("", status_code=201)
async def create_expected(
    body: ExpectedActivityBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate(body)
    await _require_cameras_in_scope(body.camera_ids, user, db)
    row = ExpectedActivity(
        name=body.name,
        subject_kind=body.subject_kind,
        subject_key=body.subject_key if body.subject_kind == "person" else None,
        camera_ids=[str(c) for c in body.camera_ids],
        weekdays=sorted(set(body.weekdays)),
        start_time=body.start_time,
        end_time=body.end_time,
        grace_minutes=body.grace_minutes,
        active_modes=body.active_modes,
        enabled=body.enabled,
        created_by_user_id=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


async def _get_in_scope(expected_id: uuid.UUID, user: User, db: AsyncSession) -> ExpectedActivity:
    row = await db.get(ExpectedActivity, expected_id)
    if row is None:
        raise HTTPException(status_code=404, detail="expectation not found")
    allowed = await allowed_camera_ids(user, db)
    if not _visible(row, allowed):
        raise HTTPException(status_code=404, detail="expectation not found")
    return row


@router.patch("/{expected_id}")
async def update_expected(
    expected_id: uuid.UUID,
    body: ExpectedActivityBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_in_scope(expected_id, user, db)
    _validate(body)
    await _require_cameras_in_scope(body.camera_ids, user, db)
    row.name = body.name
    row.subject_kind = body.subject_kind
    row.subject_key = body.subject_key if body.subject_kind == "person" else None
    row.camera_ids = [str(c) for c in body.camera_ids]
    row.weekdays = sorted(set(body.weekdays))
    row.start_time = body.start_time
    row.end_time = body.end_time
    row.grace_minutes = body.grace_minutes
    row.active_modes = body.active_modes
    row.enabled = body.enabled
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.delete("/{expected_id}", status_code=204)
async def delete_expected(
    expected_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_in_scope(expected_id, user, db)
    await db.delete(row)
    await db.commit()
    return None
