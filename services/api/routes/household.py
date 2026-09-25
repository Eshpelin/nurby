"""Household mode: is anyone home? (#184)

The mode itself is an app setting, because that is what the rule engine
reads once per tick. This router owns changing it, recording who changed
it, and telling the clients what the change silenced.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
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


# ── Household knowledge: capture / review / use loop (#185) ───────────
#
# HouseholdFact is the store. Curator-learned facts are source="agent"
# (candidate until evidence establishes them; a person accepts or rejects
# each proposal); facts a person adds here are source="user", established
# immediately, and the curator never touches them. Only established facts
# feed household context, and only established facts with a schedule and
# an explicit person-confirmed suppression arm mute alerts.
#
# Invariants carried over from #286: nothing here is auto-deleted by the
# system — hard delete is this endpoint, on explicit user action only —
# and the curator's may_modify gate (services/agent/curator.py) is the
# single authority on what it may rewrite.

from pydantic import BaseModel, Field  # noqa: E402

from shared.camera_access import (  # noqa: E402
    ALL,
    allowed_camera_ids,
    apply_camera_filter,
    require_camera_in_scope,
)
from shared.fact_schedule import (  # noqa: E402
    normalize_days,
    normalize_window,
    schedule_summary,
    suppression_armed,
)
from shared.models import (  # noqa: E402
    Camera,
    EntityAssociation,
    Observation,
    Person,
    Vehicle,
)

ENTITY_KINDS = ("household", "person", "vehicle", "camera")

FACT_STATUSES = ("candidate", "established", "archived", "rejected")


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _uuid_str(value) -> str | None:
    return str(value) if value else None


class ScheduleBody(BaseModel):
    days: list[int] = Field(min_length=1, max_length=7)
    start_minute: int
    end_minute: int
    tz: str | None = Field(default=None, max_length=64)


class FactCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="note", max_length=32)
    entity_kind: str | None = Field(default=None, max_length=16)
    entity_key: str | None = Field(default=None, max_length=255)
    schedule: ScheduleBody | None = None
    # Arm alert suppression in the same explicit act that creates the note
    # (the agent confirm-card flow). Requires a valid schedule; recorded
    # against the confirming user and logged.
    suppress_alerts: bool = False
    # web | api | agent_chat — recorded so the household can see where a
    # note came from. The confirm-card flow passes agent_chat, which makes
    # the chat confirmation the explicit act the issue requires.
    via: str | None = Field(default=None, max_length=32)


class FactUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    # enabled toggles established<->archived; pinned protects from the curator.
    enabled: bool | None = None
    pinned: bool | None = None
    entity_kind: str | None = Field(default=None, max_length=16)
    entity_key: str | None = Field(default=None, max_length=255)
    # Providing schedule replaces it; clear_schedule=true removes it.
    schedule: ScheduleBody | None = None
    clear_schedule: bool = False


class FactDecision(BaseModel):
    decision: str  # accept | reject
    reason: str | None = Field(default=None, max_length=2000)


class SuppressionUpdate(BaseModel):
    enabled: bool


def _schedule_columns(body: ScheduleBody) -> dict:
    days = normalize_days(body.days)
    window = normalize_window(body.start_minute, body.end_minute)
    if days is None or window is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid schedule: days must be weekday ints 0-6 (Monday=0) "
                "and the window must be a start<end minute range within one day"
            ),
        )
    return {
        "schedule_days": days,
        "schedule_start_minute": window[0],
        "schedule_end_minute": window[1],
        "schedule_tz": (body.tz or "").strip() or None,
    }


async def _entity_labels(db: AsyncSession, facts) -> dict:
    """``{(entity_kind, entity_key): label}`` for every attached fact.

    One small query per kind, not per fact: the knowledge page lists tens
    of rows, and N+1 label lookups would show up on exactly the screen
    people leave open.
    """
    wanted: dict[str, set[str]] = {}
    for f in facts:
        kind = getattr(f, "entity_kind", None)
        key = getattr(f, "entity_key", None)
        if kind in ("person", "vehicle", "camera") and key:
            wanted.setdefault(kind, set()).add(key)
    labels: dict[tuple[str, str], str] = {}

    async def _lookup(model, column, keys, kind):
        try:
            ids = {uuid.UUID(k) for k in keys}
        except ValueError:
            return
        rows = (
            await db.execute(select(model.id, column).where(model.id.in_(ids)))
        ).all()
        for row_id, name in rows:
            labels[(kind, str(row_id))] = name

    person_ids = wanted.get("person") or set()
    if person_ids:
        await _lookup(Person, Person.display_name, person_ids, "person")
    vehicle_ids = wanted.get("vehicle") or set()
    if vehicle_ids:
        await _lookup(Vehicle, Vehicle.display_name, vehicle_ids, "vehicle")
    camera_ids = wanted.get("camera") or set()
    if camera_ids:
        await _lookup(Camera, Camera.name, camera_ids, "camera")
    return labels


def _fact_view(f: HouseholdFact, labels: dict | None = None) -> dict:
    labels = labels or {}
    # getattr with defaults: rows predate #185's columns in old test
    # fixtures, and the columns are nullable anyway.
    entity_kind = getattr(f, "entity_kind", None)
    entity_key = getattr(f, "entity_key", None)
    entity_label = None
    if entity_kind and entity_key:
        entity_label = labels.get((entity_kind, entity_key))
        if entity_kind == "household":
            entity_label = entity_label or "Household"
    has_schedule = getattr(f, "schedule_days", None) is not None
    last_suppressed = getattr(f, "last_suppressed_at", None)
    return {
        "id": str(f.id),
        "text": f.text,
        "kind": f.kind,
        "source": f.source,          # user | agent
        "status": f.status,          # established | candidate | archived | rejected
        "enabled": f.status == "established",
        "pinned": f.pinned,
        "evidence_count": f.evidence_count,
        "entity_kind": entity_kind,
        "entity_key": entity_key,
        "entity_label": entity_label,
        "schedule": {
            "days": f.schedule_days,
            "start_minute": f.schedule_start_minute,
            "end_minute": f.schedule_end_minute,
            "tz": f.schedule_tz,
            "summary": schedule_summary(f),
        }
        if has_schedule
        else None,
        # suppression_active is computed by shared.fact_schedule at alert
        # time; here we report whether the note is armed, so the UI can
        # show "can mute alerts" even outside the window.
        "suppresses_alerts": bool(getattr(f, "suppresses_alerts", False)),
        "suppression_armed": suppression_armed(f),
        "suppression_hit_count": int(getattr(f, "suppression_hit_count", 0) or 0),
        "last_suppressed_at": last_suppressed.isoformat() if last_suppressed else None,
        "created_via": getattr(f, "created_via", None),
        "created_by_user_id": _uuid_str(getattr(f, "created_by_user_id", None)),
        "updated_by_user_id": _uuid_str(getattr(f, "updated_by_user_id", None)),
        "established_at": _iso(getattr(f, "established_at", None)),
        "rejected_at": _iso(getattr(f, "rejected_at", None)),
        "rejection_reason": getattr(f, "rejection_reason", None),
        "created_at": _iso(f.created_at),
        "updated_at": _iso(getattr(f, "updated_at", None)),
        # kept for #286 clients: "updated" here means last confirmed.
        "last_confirmed_at": _iso(f.last_confirmed_at),
    }


async def _list_scope_filters(
    q,
    user: User,
    db: AsyncSession,
    *,
    status: str | None,
    source: str | None,
    kind: str | None,
    entity_kind: str | None,
    entity_key: str | None,
    camera_id: str | None,
    text_query: str | None,
    include_archived: bool,
):
    """Shared WHERE-building for the list endpoint. Raises 400 on a bad
    filter value and 404 when camera_id is not the caller's to see."""
    if status:
        wanted = {s.strip() for s in status.split(",") if s.strip()}
        unknown = wanted - set(FACT_STATUSES)
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown status: {sorted(unknown)}")
        q = q.where(HouseholdFact.status.in_(wanted))
    else:
        # Historic default (#286): rejected facts stay hidden unless asked
        # for by name — a rejection is settled, not pending attention.
        q = q.where(HouseholdFact.status != "rejected")
        if not include_archived:
            q = q.where(HouseholdFact.status != "archived")
    if source:
        q = q.where(HouseholdFact.source == source)
    if kind:
        q = q.where(HouseholdFact.kind == kind)
    if entity_kind:
        if entity_kind not in ENTITY_KINDS:
            raise HTTPException(status_code=400, detail=f"unknown entity_kind: {entity_kind}")
        q = q.where(HouseholdFact.entity_kind == entity_kind)
    if entity_key:
        q = q.where(HouseholdFact.entity_key == entity_key)
    if text_query:
        q = q.where(HouseholdFact.text.ilike(f"%{text_query}%"))
    if camera_id:
        # Camera-attached notes for one camera. Scoped callers may only
        # ask about cameras they can see, so a foreign id is a 404, the
        # same answer the rest of the API gives.
        allowed = await allowed_camera_ids(user, db)
        if allowed is not ALL and camera_id not in {str(c) for c in allowed}:
            raise HTTPException(status_code=404, detail="camera not found")
        q = q.where(HouseholdFact.entity_kind == "camera")
        q = q.where(HouseholdFact.entity_key == camera_id)
    else:
        # Camera-scope ACL: a camera-attached fact is as visible as the
        # camera. Household/person/vehicle notes are shared household
        # knowledge; their *evidence* is still scoped (see /evidence).
        allowed = await allowed_camera_ids(user, db)
        if allowed is not ALL:
            if not allowed:
                q = q.where(HouseholdFact.entity_kind != "camera")
            else:
                q = q.where(
                    (HouseholdFact.entity_kind != "camera")
                    | HouseholdFact.entity_key.in_(str(c) for c in allowed)
                )
    return q


@router.get("/facts")
async def list_facts(
    include_archived: bool = True,
    status: str | None = None,
    source: str | None = None,
    kind: str | None = None,
    entity_kind: str | None = None,
    entity_key: str | None = None,
    camera_id: str | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything Nurby remembers, newest first, filtered.

    Rejected facts are hidden unless ``status=rejected`` (they are
    permanently dismissed); archived facts are shown unless
    ``include_archived=false``. Camera-attached facts respect the
    caller's camera scope."""
    query = await _list_scope_filters(
        select(HouseholdFact),
        user,
        db,
        status=status,
        source=source,
        kind=kind,
        entity_kind=entity_kind,
        entity_key=entity_key,
        camera_id=camera_id,
        text_query=q,
        include_archived=include_archived,
    )
    query = query.order_by(HouseholdFact.pinned.desc(), HouseholdFact.created_at.desc())
    rows = (await db.execute(query)).scalars().all()
    labels = await _entity_labels(db, rows)
    return [_fact_view(f, labels) for f in rows]


async def _get_fact(fact_id: uuid.UUID, db: AsyncSession) -> HouseholdFact:
    fact = await db.get(HouseholdFact, fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return fact


async def _resolve_entity(
    db: AsyncSession,
    user: User,
    entity_kind: str | None,
    entity_key: str | None,
) -> tuple[str | None, str | None]:
    """Validate an attachment against real rows and return the canonical
    pair. Household needs no key; person/vehicle/camera must exist, and a
    camera must be in the caller's scope."""
    if entity_kind is None:
        if entity_key:
            raise HTTPException(status_code=400, detail="entity_key requires entity_kind")
        # No attach point means the household itself, explicitly.
        return "household", "household"
    if entity_kind not in ENTITY_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown entity_kind: {entity_kind}")
    if entity_kind == "household":
        return "household", "household"
    if not entity_key:
        raise HTTPException(status_code=400, detail=f"entity_key required for {entity_kind}")
    if entity_kind == "camera":
        try:
            camera_uuid = uuid.UUID(entity_key)
        except ValueError:
            raise HTTPException(status_code=400, detail="entity_key must be a camera UUID")
        await require_camera_in_scope(user, db, camera_uuid, detail="camera not found")
        camera = await db.get(Camera, camera_uuid)
        if camera is None:
            raise HTTPException(status_code=404, detail="camera not found")
        return "camera", str(camera.id)
    model, label = (Person, "person") if entity_kind == "person" else (Vehicle, "vehicle")
    try:
        entity_uuid = uuid.UUID(entity_key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"entity_key must be a {label} UUID")
    row = await db.get(model, entity_uuid)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return entity_kind, str(entity_uuid)


@router.post("/facts", status_code=201)
async def create_fact(
    body: FactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a user-authored note. source="user" + status="established" so it
    feeds answers immediately and the curator never rewrites it. Alert
    suppression arms only here (with ``suppress_alerts`` + a valid
    schedule, an explicit part of the creating confirmation) or via the
    dedicated /suppression endpoint — never as an implicit side effect."""
    now = datetime.now(timezone.utc)
    via = (body.via or "web").strip() or "web"
    if via not in ("web", "api", "agent_chat"):
        via = "api"
    entity_kind, entity_key = await _resolve_entity(
        db, user, body.entity_kind, body.entity_key
    )
    schedule = _schedule_columns(body.schedule) if body.schedule else None
    armed = False
    if body.suppress_alerts:
        if not schedule:
            raise HTTPException(
                status_code=400,
                detail="suppress_alerts requires a schedule",
            )
        armed = True
    fact = HouseholdFact(
        text=body.text.strip(),
        subject_key=f"user:{uuid.uuid4().hex[:16]}",
        kind=(body.kind or "note").strip() or "note",
        source="user",
        status="established",
        pinned=False,
        evidence_count=0,
        last_confirmed_at=now,
        established_at=now,
        entity_kind=entity_kind,
        entity_key=entity_key,
        created_by_user_id=user.id,
        created_via=via,
        suppresses_alerts=armed,
        suppression_confirmed_at=now if armed else None,
        suppression_confirmed_by_user_id=user.id if armed else None,
        **(schedule or {}),
    )
    db.add(fact)
    await db.commit()
    await db.refresh(fact)
    if armed:
        logger.info(
            "alert suppression ARMED on new fact %s by user %s", fact.id, user.id
        )
    return _fact_view(fact, await _entity_labels(db, [fact]))


@router.patch("/facts/{fact_id}")
async def update_fact(
    fact_id: uuid.UUID,
    body: FactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit / disable / pin / re-attach a note. A user edit is durable; because
    the curator only auto-modifies source="agent" rows, editing here (which
    does not change source) sticks."""
    fact = await _get_fact(fact_id, db)
    now = datetime.now(timezone.utc)
    if body.text is not None:
        fact.text = body.text.strip()
        fact.last_confirmed_at = now
    if body.pinned is not None:
        fact.pinned = body.pinned
    if body.entity_kind is not None or body.entity_key is not None:
        kind = body.entity_kind if body.entity_kind is not None else fact.entity_kind
        key = body.entity_key if body.entity_key is not None else fact.entity_key
        fact.entity_kind, fact.entity_key = await _resolve_entity(db, user, kind, key)
    if body.clear_schedule:
        fact.schedule_days = None
        fact.schedule_start_minute = None
        fact.schedule_end_minute = None
        fact.schedule_tz = None
        # An un-scheduled note cannot mute anything; disarm rather than
        # leave an armed flag pointing at nothing.
        fact.suppresses_alerts = False
        fact.suppression_confirmed_at = None
    elif body.schedule is not None:
        for column, value in _schedule_columns(body.schedule).items():
            setattr(fact, column, value)
        if fact.suppresses_alerts:
            # The window changed under an armed note; require a fresh
            # confirm so nobody widens a muting window without noticing.
            fact.suppression_confirmed_at = None
            fact.suppresses_alerts = False
    if body.enabled is not None:
        if body.enabled:
            fact.status = "established"
            fact.archived_at = None
            fact.established_at = fact.established_at or now
        else:
            fact.status = "archived"
            fact.archived_at = now
    fact.updated_at = now
    fact.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(fact)
    return _fact_view(fact)


@router.post("/facts/{fact_id}/decision")
async def decide_fact(
    fact_id: uuid.UUID,
    body: FactDecision,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept or reject a proposal. Accept promotes candidate→established;
    reject is permanent for any live status — a rejected fact is never
    re-proposed, because the row still exists and the curator's
    may_modify gate refuses rejected rows (and upserts find the row)."""
    fact = await _get_fact(fact_id, db)
    now = datetime.now(timezone.utc)
    decision = (body.decision or "").strip().lower()
    if decision == "accept":
        if fact.status != "candidate":
            raise HTTPException(status_code=409, detail=f"cannot accept a {fact.status} fact")
        fact.status = "established"
        fact.established_at = now
        fact.last_confirmed_at = now
    elif decision == "reject":
        if fact.status == "rejected":
            raise HTTPException(status_code=409, detail="fact already rejected")
        # Rejected notes stop mattering entirely, including any alert
        # suppression they armed.
        fact.status = "rejected"
        fact.rejected_at = now
        fact.rejection_reason = (body.reason or "").strip() or None
        fact.suppresses_alerts = False
        fact.suppression_confirmed_at = None
    else:
        raise HTTPException(status_code=400, detail="decision must be accept or reject")
    fact.updated_at = now
    fact.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(fact)
    logger.info(
        "household fact %s %s by user %s", fact.id, decision, user.id
    )
    return _fact_view(fact)


@router.post("/facts/{fact_id}/restore")
async def restore_fact(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bring an archived fact back. Archive is recoverable by design;
    restore is the recover step. Rejected facts stay rejected — that door
    is closed on purpose."""
    fact = await _get_fact(fact_id, db)
    if fact.status == "rejected":
        raise HTTPException(status_code=409, detail="rejected facts cannot be restored")
    if fact.status != "archived":
        raise HTTPException(status_code=409, detail=f"fact is {fact.status}, not archived")
    now = datetime.now(timezone.utc)
    fact.status = "established"
    fact.archived_at = None
    fact.established_at = fact.established_at or now
    fact.last_confirmed_at = now
    fact.updated_at = now
    fact.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(fact)
    return _fact_view(fact)


@router.post("/facts/{fact_id}/suppression")
async def set_fact_suppression(
    fact_id: uuid.UUID,
    body: SuppressionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Arm or disarm alert suppression for a schedule-bearing note.

    This is the explicit confirmation the issue requires: a note never
    mutes an alert because Nurby learned it, only because a person
    pressed confirm on this exact effect. Requires a valid schedule and
    an established note; disarming is the same endpoint with false, so
    the effect stays visible and reversible."""
    fact = await _get_fact(fact_id, db)
    if body.enabled:
        if fact.status != "established":
            raise HTTPException(
                status_code=409, detail="only established facts can suppress alerts"
            )
        if (
            normalize_days(fact.schedule_days) is None
            or normalize_window(fact.schedule_start_minute, fact.schedule_end_minute) is None
        ):
            raise HTTPException(status_code=409, detail="fact has no valid schedule")
        fact.suppresses_alerts = True
        fact.suppression_confirmed_at = datetime.now(timezone.utc)
        fact.suppression_confirmed_by_user_id = user.id
        logger.info("alert suppression ARMED on fact %s by user %s", fact.id, user.id)
    else:
        fact.suppresses_alerts = False
        fact.suppression_confirmed_at = None
        fact.suppression_confirmed_by_user_id = None
        logger.info("alert suppression disarmed on fact %s by user %s", fact.id, user.id)
    fact.updated_at = datetime.now(timezone.utc)
    fact.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(fact)
    return _fact_view(fact)


@router.get("/facts/{fact_id}/evidence")
async def fact_evidence(
    fact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Why Nurby believes this: the supporting rows behind a fact.

    Association references resolve to the pattern (days seen, hours,
    first/last observed); observation references resolve to bounded
    stubs (camera, time, description) filtered to the caller's camera
    scope. A user note has no evidence — it *is* the household speaking."""
    fact = await _get_fact(fact_id, db)
    allowed = await allowed_camera_ids(user, db)
    refs = fact.evidence_refs or []
    out: list[dict] = []

    assoc_ids = [r["id"] for r in refs if r.get("kind") == "association"]
    if assoc_ids:
        rows = (
            await db.execute(
                select(EntityAssociation).where(EntityAssociation.id.in_(assoc_ids))
            )
        ).scalars().all()
        by_id = {str(row.id): row for row in rows}
        for ref in refs:
            if ref.get("kind") != "association":
                continue
            row = by_id.get(str(ref.get("id")))
            if row is None:
                out.append({"kind": "association", "id": str(ref.get("id")), "missing": True})
                continue
            hours = sorted(
                int(h) for h, c in (row.hour_histogram or {}).items() if int(c) > 0
            )
            out.append({
                "kind": "association",
                "id": str(row.id),
                "relation": row.relation,
                "subject_kind": row.subject_kind,
                "subject_key": row.subject_key,
                "object_kind": row.object_kind,
                "object_key": row.object_key,
                "object_label": row.object_label or row.object_key,
                "source": row.source,
                "status": row.status,
                "distinct_days": row.distinct_days,
                "evidence_count": row.evidence_count,
                "usual_hours": hours,
                "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            })

    observation_ids = [r["id"] for r in refs if r.get("kind") in ("observation", "event")]
    if observation_ids:
        query = apply_camera_filter(
            select(Observation).where(Observation.id.in_(observation_ids)),
            allowed,
            Observation.camera_id,
        )
        rows = (await db.execute(query)).scalars().all()
        by_id = {str(row.id): row for row in rows}
        for ref in refs:
            if ref.get("kind") not in ("observation", "event"):
                continue
            row = by_id.get(str(ref.get("id")))
            if row is None:
                # Either gone or out of the caller's camera scope; both
                # look the same from here on purpose.
                out.append({"kind": ref.get("kind"), "id": str(ref.get("id")), "unavailable": True})
                continue
            out.append({
                "kind": "observation",
                "id": str(row.id),
                "camera_id": str(row.camera_id),
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                "vlm_description": row.vlm_description,
            })
    return {
        "fact_id": str(fact.id),
        "evidence_count": fact.evidence_count,
        "refs": out,
    }


@router.delete("/facts/{fact_id}", status_code=204)
async def delete_fact(
    fact_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prune a fact for good. The only hard delete in the fact lifecycle,
    and always a person's explicit action."""
    fact = await db.get(HouseholdFact, fact_id)
    if fact is not None:
        await db.delete(fact)
        await db.commit()
    return None
