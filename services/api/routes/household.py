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
from shared.models import HouseholdFact, HouseholdModeChange, Rule, User
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


# ── Household memory: read/add/edit/prune what Nurby knows (#286) ──────
#
# HouseholdFact is the store. Curator-learned facts are source="agent"
# (auto-managed, never overwriting a person's edits); facts a person adds
# here are source="user" and the curator never touches them. Disabling a
# fact archives it (status="archived") so it stops feeding answers but stays
# visible until deleted; only status="established" facts feed household
# context.

from pydantic import BaseModel, Field  # noqa: E402


class FactCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="note", max_length=32)


class FactUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    # enabled toggles established<->archived; pinned protects from the curator.
    enabled: bool | None = None
    pinned: bool | None = None


def _fact_view(f: HouseholdFact) -> dict:
    return {
        "id": str(f.id),
        "text": f.text,
        "kind": f.kind,
        "source": f.source,          # user | agent
        "status": f.status,          # established | candidate | archived | rejected
        "enabled": f.status == "established",
        "pinned": f.pinned,
        "evidence_count": f.evidence_count,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "updated_at": f.last_confirmed_at.isoformat() if f.last_confirmed_at else None,
    }


@router.get("/facts")
async def list_facts(
    include_archived: bool = True,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything Nurby remembers about the household, newest first.

    Rejected facts are hidden (they are permanently dismissed); archived facts
    are shown unless ``include_archived=false`` so the Memory tab can list
    disabled entries for restore/delete."""
    q = select(HouseholdFact).where(HouseholdFact.status != "rejected")
    if not include_archived:
        q = q.where(HouseholdFact.status != "archived")
    q = q.order_by(HouseholdFact.pinned.desc(), HouseholdFact.created_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_fact_view(f) for f in rows]


@router.post("/facts", status_code=201)
async def create_fact(
    body: FactCreate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a user-authored fact. source="user" + status="established" so it
    feeds answers immediately and the curator never rewrites it."""
    now = datetime.now(timezone.utc)
    fact = HouseholdFact(
        text=body.text.strip(),
        subject_key=f"user:{uuid.uuid4().hex[:16]}",
        kind=(body.kind or "note").strip() or "note",
        source="user",
        status="established",
        pinned=False,
        evidence_count=0,
        last_confirmed_at=now,
    )
    db.add(fact)
    await db.commit()
    await db.refresh(fact)
    return _fact_view(fact)


@router.patch("/facts/{fact_id}")
async def update_fact(
    fact_id: uuid.UUID,
    body: FactUpdate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit / disable / pin a fact. A user edit is durable; because the curator
    only auto-modifies source="agent" rows, editing here (which does not change
    source) sticks."""
    from fastapi import HTTPException

    fact = await db.get(HouseholdFact, fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    if body.text is not None:
        fact.text = body.text.strip()
        fact.last_confirmed_at = datetime.now(timezone.utc)
    if body.pinned is not None:
        fact.pinned = body.pinned
    if body.enabled is not None:
        if body.enabled:
            fact.status = "established"
            fact.archived_at = None
        else:
            fact.status = "archived"
            fact.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(fact)
    return _fact_view(fact)


@router.delete("/facts/{fact_id}", status_code=204)
async def delete_fact(
    fact_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prune a fact for good."""
    fact = await db.get(HouseholdFact, fact_id)
    if fact is not None:
        await db.delete(fact)
        await db.commit()
    return None
