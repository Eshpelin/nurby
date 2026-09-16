"""Household mode: is anyone home? (#184)

The mode itself is an app setting, because that is what the rule engine
reads once per tick. This router owns changing it, recording who changed
it, and telling the clients what the change silenced.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.app_settings import get_setting, set_setting
from shared.auth import get_current_user
from shared.database import get_db
from shared.household_mode import (
    DEFAULT_MODE,
    MODE_HINTS,
    MODE_LABELS,
    MODES,
    is_mode,
    rule_active_in,
)
from shared.models import HouseholdModeChange, Rule, User
from shared.schemas import (
    HouseholdModeChangeResponse,
    HouseholdModeResponse,
    HouseholdModeUpdate,
)

router = APIRouter()
logger = logging.getLogger("nurby.api.household")


async def current_mode() -> str:
    value = await get_setting("household_mode")
    return value if is_mode(value) else DEFAULT_MODE


async def _silenced_count(db: AsyncSession, mode: str) -> int:
    rows = (await db.execute(select(Rule.conditions).where(Rule.enabled.is_(True)))).all()
    return sum(1 for (conditions,) in rows if not rule_active_in(conditions, mode))


async def _history(db: AsyncSession, limit: int) -> list[HouseholdModeChangeResponse]:
    q = (
        select(HouseholdModeChange, User.display_name)
        .outerjoin(User, User.id == HouseholdModeChange.changed_by_user_id)
        .order_by(HouseholdModeChange.changed_at.desc())
        .limit(limit)
    )
    out = []
    for change, name in (await db.execute(q)).all():
        item = HouseholdModeChangeResponse.model_validate(change)
        item.changed_by_name = name
        out.append(item)
    return out


async def _build_response(db: AsyncSession, mode: str) -> HouseholdModeResponse:
    history = await _history(db, 20)
    latest = history[0] if history and history[0].mode == mode else None
    return HouseholdModeResponse(
        mode=mode,
        since=latest.changed_at if latest else None,
        source=latest.source if latest else None,
        modes=[{"key": m, "label": MODE_LABELS[m], "hint": MODE_HINTS[m]} for m in MODES],
        history=history,
        silenced_rule_count=await _silenced_count(db, mode),
    )


@router.get("/mode", response_model=HouseholdModeResponse)
async def get_mode(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HouseholdModeResponse:
    return await _build_response(db, await current_mode())


async def change_mode(
    db: AsyncSession,
    *,
    mode: str,
    source: str,
    user_id: uuid.UUID | None,
    note: str | None,
) -> HouseholdModeChange | None:
    """Set the mode and record the change. Returns the history row, or
    None when the mode was already set (no row is written for a no-op, so
    tapping the active chip twice does not litter the timeline)."""
    previous = await current_mode()
    if previous == mode:
        return None
    await set_setting("household_mode", mode)
    row = HouseholdModeChange(
        mode=mode,
        previous_mode=previous,
        source=source,
        changed_by_user_id=user_id,
        note=(note or "").strip() or None,
        changed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("household mode %s -> %s (%s)", previous, mode, source)
    return row


@router.put("/mode", response_model=HouseholdModeResponse)
async def set_mode(
    body: HouseholdModeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HouseholdModeResponse:
    await change_mode(db, mode=body.mode, source="manual", user_id=user.id, note=body.note)
    return await _build_response(db, body.mode)
