"""Reversible alert-tuning endpoints (#196).

Reads a rule's reviewed alerts (#195), proposes reversible tuning with
sample sizes and example events, previews a change against history, and
applies an accepted change while returning the previous value so the caller
can undo. No automatic silent changes: applying always requires this
explicit call.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.events import tuning
from shared.auth import get_current_user
from shared.database import get_db
from shared.models import Event, Rule, User
from shared.models.rules import EventFeedback

router = APIRouter()

# Fields an accept is allowed to touch, mapped to how they are applied.
_APPLIABLE = {"cooldown_seconds", "conditions.min_confidence", "conditions.time_window", "severity"}


async def _gather_events(db: AsyncSession, rule_id: uuid.UUID, days: int) -> list[dict]:
    """A rule's events in the window, each with its reviewed feedback (if any)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(Event).where(Event.rule_id == rule_id, Event.fired_at >= since)
        )
    ).scalars().all()
    if not rows:
        return []
    fb_rows = (
        await db.execute(
            select(EventFeedback).where(EventFeedback.event_id.in_([e.id for e in rows]))
        )
    ).scalars().all()
    fb_by_event = {fb.event_id: fb for fb in fb_rows}
    out = []
    for e in rows:
        fb = fb_by_event.get(e.id)
        out.append({
            "id": str(e.id),
            "fired_at": e.fired_at,
            "payload": e.payload or {},
            "feedback": ({"rating": fb.rating, "reason": fb.reason} if fb else None),
        })
    return out


@router.get("/rules/{rule_id}/tuning-suggestions")
async def get_tuning_suggestions(
    rule_id: uuid.UUID,
    days: int = 30,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reversible tuning proposals for a rule, from reviewed alerts."""
    rule = await db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    events = await _gather_events(db, rule_id, days)
    rule_dict = {
        "cooldown_seconds": rule.cooldown_seconds,
        "conditions": rule.conditions or {},
        "severity": rule.severity,
    }
    suggestions = [s.to_dict() for s in tuning.analyze(rule_dict, events)]
    reviewed = sum(1 for e in events if e["feedback"])
    return {
        "rule_id": str(rule_id),
        "reviewed_sample": reviewed,
        "suggestions": suggestions,
        "note": "Nothing changes until you accept a suggestion." if suggestions
                else "Not enough reviewed alerts yet to suggest tuning.",
    }


class PreviewRequest(BaseModel):
    suggestion: dict
    days: int = 30


@router.post("/rules/{rule_id}/tuning-suggestions/preview")
async def preview_tuning(
    rule_id: uuid.UUID,
    body: PreviewRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replay a proposed change over the rule's historical events."""
    rule = await db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    events = await _gather_events(db, rule_id, body.days)
    return tuning.preview(body.suggestion, events)


class ApplyRequest(BaseModel):
    field: str
    proposed_value: object


@router.post("/rules/{rule_id}/apply-tuning")
async def apply_tuning(
    rule_id: uuid.UUID,
    body: ApplyRequest,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply an accepted change and return the previous value for undo.

    Reversible by construction: the response carries ``previous_value``; undo
    is a second call to this endpoint with that value. Never called
    implicitly, so no silent changes.
    """
    if body.field not in _APPLIABLE:
        raise HTTPException(status_code=400, detail=f"field not tunable: {body.field}")
    rule = await db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")

    if body.field == "cooldown_seconds":
        previous = rule.cooldown_seconds
        rule.cooldown_seconds = int(body.proposed_value)
    elif body.field == "severity":
        previous = rule.severity
        if body.proposed_value not in ("alert", "detection"):
            raise HTTPException(status_code=400, detail="severity must be alert or detection")
        rule.severity = str(body.proposed_value)
    elif body.field == "conditions.min_confidence":
        conditions = dict(rule.conditions or {})
        previous = conditions.get("min_confidence")
        conditions["min_confidence"] = float(body.proposed_value)
        rule.conditions = conditions
    elif body.field == "conditions.time_window":
        conditions = dict(rule.conditions or {})
        previous = {"time_after": conditions.get("time_after"),
                    "time_before": conditions.get("time_before")}
        pv = body.proposed_value or {}
        conditions["time_after"] = pv.get("time_after")
        conditions["time_before"] = pv.get("time_before")
        rule.conditions = conditions
    await db.commit()
    return {"applied": True, "field": body.field, "previous_value": previous,
            "note": "To undo, apply this field again with previous_value."}
