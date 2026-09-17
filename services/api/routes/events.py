import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user, require_admin
from shared.camera_access import ALL, AllowedCameras, allowed_camera_ids, apply_camera_filter, require_camera_in_scope
from shared.database import get_db
from shared.models import Camera, Event, EventFeedback, EventNote, Observation, Person, Rule, User
from shared.paths import escape_like
from shared.schemas import (
    EventFeedbackCreate,
    EventFeedbackResponse,
    EventNoteCreate,
    EventNoteResponse,
    EventResponse,
)

router = APIRouter()


def _not_review_excluded(camera_id_col):
    """Filter clause keeping only rows whose camera is not hidden from the
    review/alerts feed. Rows with a null camera_id (no source camera) are
    kept, since `NULL NOT IN (...)` would otherwise drop them."""
    excluded = select(Camera.id).where(Camera.exclude_from_review.is_(True))
    return or_(camera_id_col.is_(None), camera_id_col.not_in(excluded))


async def _serialize_note(db: AsyncSession, note: EventNote) -> dict:
    """Resolve the author's display name for the EventNote response."""
    display_name: str | None = None
    if note.author_user_id is not None:
        author = await db.get(User, note.author_user_id)
        if author is not None:
            display_name = author.display_name or author.email
    return {
        "id": note.id,
        "event_id": note.event_id,
        "author_user_id": note.author_user_id,
        "author_display_name": display_name,
        "source": note.source,
        "text": note.text,
        "telegram_message_id": note.telegram_message_id,
        "created_at": note.created_at,
    }


async def _serialize_feedback(db: AsyncSession, fb: EventFeedback) -> dict:
    """Resolve the reviewer's display name for the feedback response."""
    display_name: str | None = None
    if fb.user_id is not None:
        reviewer = await db.get(User, fb.user_id)
        if reviewer is not None:
            display_name = reviewer.display_name or reviewer.email
    return {
        "id": fb.id,
        "event_id": fb.event_id,
        "user_id": fb.user_id,
        "reviewer_display_name": display_name,
        "rating": fb.rating,
        "reason": fb.reason,
        "created_at": fb.created_at,
        "updated_at": fb.updated_at,
    }


@router.get("", response_model=list[EventResponse])
async def list_events(
    rule_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    query = apply_camera_filter(
        select(Event)
        .where(_not_review_excluded(Event.camera_id))
        .order_by(Event.fired_at.desc()),
        allowed,
        Event.camera_id,
    ).limit(limit).offset(offset)
    if rule_id:
        query = query.where(Event.rule_id == rule_id)
    result = await db.execute(query)
    return result.scalars().all()


async def _filtered_events_query(
    db: AsyncSession,
    *,
    rule_id: uuid.UUID | None = None,
    camera_id: uuid.UUID | None = None,
    status: str | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
    person_id: uuid.UUID | None = None,
    label: str | None = None,
    acked: bool | None = None,
    severity: str | None = None,
    allowed: AllowedCameras = ALL,
):
    """Shared filter builder for /history and /export.csv. Returns the
    query, or None when a person filter resolves to nobody (no rows).

    ``allowed`` is the per-user camera ACL (issue #40); it defaults to
    ``ALL`` (no filter) so existing callers and tests are unaffected."""
    query = apply_camera_filter(
        select(Event)
        .where(_not_review_excluded(Event.camera_id))
        .order_by(Event.fired_at.desc()),
        allowed,
        Event.camera_id,
    )
    if severity in ("alert", "detection"):
        query = query.where(Event.severity == severity)
    if rule_id:
        query = query.where(Event.rule_id == rule_id)
    if status:
        query = query.where(Event.action_status == status)
    if from_:
        query = query.where(Event.fired_at >= from_)
    if to:
        query = query.where(Event.fired_at <= to)
    if acked is True:
        query = query.where(Event.acked_at.is_not(None))
    elif acked is False:
        query = query.where(Event.acked_at.is_(None))

    # camera/person/label filters all reach through the linked Observation.
    needs_obs = bool(camera_id or person_id or label)
    if needs_obs:
        query = query.join(Observation, Event.observation_id == Observation.id)
    if camera_id:
        query = query.where(Observation.camera_id == camera_id)
    if person_id:
        name = (
            await db.execute(select(Person.display_name).where(Person.id == person_id))
        ).scalars().first()
        if not name:
            return None
        query = query.where(
            cast(Observation.person_detections, String).ilike(
                f'%"person_name": "{escape_like(name)}"%', escape="\\"
            )
        )
    if label:
        query = query.where(
            cast(Observation.object_detections, String).ilike(
                f'%"label": "{escape_like(label)}"%', escape="\\"
            )
        )
    return query


@router.get("/history", response_model=list[EventResponse])
async def event_history(
    rule_id: uuid.UUID | None = Query(default=None),
    camera_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from", description="Inclusive start (ISO 8601)"),
    to: datetime | None = Query(default=None, description="Inclusive end (ISO 8601)"),
    person_id: uuid.UUID | None = Query(
        default=None, description="Filter to events whose observation names this person"
    ),
    label: str | None = Query(
        default=None, description="Filter to events whose observation carries this label"
    ),
    acked: bool | None = Query(default=None, description="true = acknowledged only, false = unreviewed only"),
    severity: str | None = Query(default=None, description="alert or detection"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """List events with optional filters for rule, camera, action status,
    time range, person, label, and acknowledged state."""
    allowed = await allowed_camera_ids(current_user, db)
    query = await _filtered_events_query(
        db, rule_id=rule_id, camera_id=camera_id, status=status, from_=from_,
        to=to, person_id=person_id, label=label, acked=acked, severity=severity,
        allowed=allowed,
    )
    if query is None:
        return []
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/export.csv")
async def export_events_csv(
    rule_id: uuid.UUID | None = Query(default=None),
    camera_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    person_id: uuid.UUID | None = Query(default=None),
    label: str | None = Query(default=None),
    acked: bool | None = Query(default=None),
    severity: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Audit/archival export of fired events. Same filters as /history,
    streamed as CSV (mirrors the transcripts export) so large histories
    do not blow API memory."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    allowed = await allowed_camera_ids(current_user, db)
    query = await _filtered_events_query(
        db, rule_id=rule_id, camera_id=camera_id, status=status, from_=from_,
        to=to, person_id=person_id, label=label, acked=acked, severity=severity,
        allowed=allowed,
    )

    columns = [
        "id", "fired_at", "rule_id", "rule_name", "camera_id", "camera_name",
        "action_status", "action_type", "action_error",
        "acked_at", "acked_via", "observation_id", "recording_id", "description",
    ]

    async def _stream():
        head = io.StringIO()
        csv.writer(head).writerow(columns)
        yield head.getvalue()
        if query is None:
            return
        # Resolve rule names once. the rule table is tiny.
        rules = {
            r.id: r.name
            for r in (await db.execute(select(Rule))).scalars().all()
        }
        result = await db.stream(query.order_by(None).order_by(Event.fired_at.asc()))
        async for ev in result.scalars():
            payload = ev.payload or {}
            buf = io.StringIO()
            csv.writer(buf).writerow([
                str(ev.id),
                ev.fired_at.isoformat() if ev.fired_at else "",
                str(ev.rule_id) if ev.rule_id else "",
                rules.get(ev.rule_id, ""),
                str(payload.get("camera_id") or ""),
                payload.get("camera_name") or "",
                ev.action_status or "",
                ev.action_type or "",
                ev.action_error or "",
                ev.acked_at.isoformat() if ev.acked_at else "",
                ev.acked_via or "",
                str(ev.observation_id) if ev.observation_id else "",
                str(ev.recording_id) if ev.recording_id else "",
                (payload.get("vlm_description") or payload.get("status_reason") or "")[:500],
            ])
            yield buf.getvalue()

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="events.csv"'},
    )


@router.get("/count")
async def events_count(
    acked: bool | None = Query(default=None),
    severity: str | None = Query(default=None),
    rule_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Count events, e.g. ?acked=false for the unreviewed badge."""
    from sqlalchemy import func as sa_func

    query = select(sa_func.count(Event.id))
    if severity in ("alert", "detection"):
        query = query.where(Event.severity == severity)
    if rule_id:
        query = query.where(Event.rule_id == rule_id)
    if from_:
        query = query.where(Event.fired_at >= from_)
    if acked is True:
        query = query.where(Event.acked_at.is_not(None))
    elif acked is False:
        query = query.where(Event.acked_at.is_(None))
    count = (await db.execute(query)).scalar_one()
    return {"count": int(count)}


@router.post("/batch-ack")
async def batch_ack(
    event_ids: list[uuid.UUID],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge many events in one call (max 500). Already-acked
    events are skipped; the first acker is preserved (same semantics as
    the single ack endpoint)."""
    if len(event_ids) > 500:
        raise HTTPException(status_code=400, detail="At most 500 events per call")
    now = datetime.now(timezone.utc)
    acked = 0
    for eid in event_ids:
        event = await db.get(Event, eid)
        if event is None or event.acked_at is not None:
            continue
        event.acked_at = now
        event.acked_by_user_id = current_user.id
        event.acked_via = "web"
        if event.acknowledged_at is None:
            event.acknowledged_at = now
        acked += 1
    await db.commit()
    return {"acked": acked, "requested": len(event_ids)}


# ── Structured alert feedback (#195) ──
# Rating an alert is independent of acknowledging it: ack means
# "seen/handled", feedback says whether the alert was useful or even
# correct. Every route here goes through the same camera scope as the
# list endpoints; a foreign event is a 404, not a 403.


@router.get("/feedback/summary")
async def feedback_summary(
    hours: int = Query(default=168, ge=1, le=8760),
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Usefulness and response-rate counts over recent alerts.

    Counts only — no footage, paths or payload content. The response
    rate denominator is every event fired in the window, so a low
    feedback rate stays visible next to the usefulness split.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    fired = await db.execute(
        select(func.count()).select_from(Event).where(Event.fired_at >= cutoff)
    )
    total_events = fired.scalar_one()

    rating_rows = (
        await db.execute(
            select(EventFeedback.rating, func.count())
            .join(Event, Event.id == EventFeedback.event_id)
            .where(Event.fired_at >= cutoff)
            .group_by(EventFeedback.rating)
        )
    ).all()
    rating_counts = {rating: count for rating, count in rating_rows}

    reason_rows = (
        await db.execute(
            select(EventFeedback.reason, func.count())
            .join(Event, Event.id == EventFeedback.event_id)
            .where(Event.fired_at >= cutoff, EventFeedback.reason.is_not(None))
            .group_by(EventFeedback.reason)
        )
    ).all()
    reason_counts = {reason: count for reason, count in reason_rows}

    reviewed_rows = (
        await db.execute(
            select(func.count(func.distinct(EventFeedback.event_id)))
            .join(Event, Event.id == EventFeedback.event_id)
            .where(Event.fired_at >= cutoff)
        )
    ).scalar_one()
    reviewers = (
        await db.execute(
            select(func.count(func.distinct(EventFeedback.user_id)))
            .join(Event, Event.id == EventFeedback.event_id)
            .where(Event.fired_at >= cutoff)
        )
    ).scalar_one()

    return {
        "window_hours": hours,
        "events_fired": total_events,
        "events_reviewed": reviewed_rows,
        "response_rate": round(reviewed_rows / total_events, 4) if total_events else None,
        "distinct_reviewers": reviewers,
        "rating_counts": {
            "useful": rating_counts.get("useful", 0),
            "correct_but_not_useful": rating_counts.get("correct_but_not_useful", 0),
            "incorrect": rating_counts.get("incorrect", 0),
        },
        "incorrect_reason_counts": {
            "wrong_object": reason_counts.get("wrong_object", 0),
            "wrong_person": reason_counts.get("wrong_person", 0),
            "duplicate": reason_counts.get("duplicate", 0),
            "timing": reason_counts.get("timing", 0),
        },
    }


@router.get("/{event_id}/feedback", response_model=list[EventFeedbackResponse])
async def list_event_feedback(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every reviewer's feedback on one event. Household members see who
    rated what; camera scope decides whether the event is visible at all."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await require_camera_in_scope(current_user, db, event.camera_id)
    rows = await db.execute(
        select(EventFeedback)
        .where(EventFeedback.event_id == event_id)
        .order_by(EventFeedback.created_at.asc())
    )
    return [await _serialize_feedback(db, fb) for fb in rows.scalars().all()]


@router.put("/{event_id}/feedback", response_model=EventFeedbackResponse)
async def set_event_feedback(
    event_id: uuid.UUID,
    body: EventFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rate an alert, or correct an earlier rating.

    One row per (event, user): a correction rewrites it. A PUT is two
    interactions — the rating and, for incorrect alerts, one optional
    reason."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await require_camera_in_scope(current_user, db, event.camera_id)

    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(
            select(EventFeedback).where(
                EventFeedback.event_id == event_id,
                EventFeedback.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.rating = body.rating
        existing.reason = body.reason
        existing.updated_at = now
        await db.commit()
        await db.refresh(existing)
        return await _serialize_feedback(db, existing)

    fb = EventFeedback(
        event_id=event_id,
        user_id=current_user.id,
        rating=body.rating,
        reason=body.reason,
        created_at=now,
        updated_at=now,
    )
    db.add(fb)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent first rating from the same user.
        await db.rollback()
        existing = (
            await db.execute(
                select(EventFeedback).where(
                    EventFeedback.event_id == event_id,
                    EventFeedback.user_id == current_user.id,
                )
            )
        ).scalar_one()
        existing.rating = body.rating
        existing.reason = body.reason
        existing.updated_at = now
        await db.commit()
        await db.refresh(existing)
        return await _serialize_feedback(db, existing)
    await db.refresh(fb)
    return await _serialize_feedback(db, fb)


@router.delete("/{event_id}/feedback", status_code=204)
async def clear_event_feedback(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw the caller's own feedback. Other reviewers are unaffected."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await require_camera_in_scope(current_user, db, event.camera_id)
    existing = (
        await db.execute(
            select(EventFeedback).where(
                EventFeedback.event_id == event_id,
                EventFeedback.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="No feedback to clear")
    await db.delete(existing)
    await db.commit()


@router.get("/{event_id}")
async def get_event(
    event_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single event with its annotation notes.

    Phase 4. The response now embeds an array of ``notes`` (web,
    telegram, api). Pre-Phase-4 callers that only read top-level
    Event fields keep working because the new key is additive.
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    notes_result = await db.execute(
        select(EventNote)
        .where(EventNote.event_id == event_id)
        .order_by(EventNote.created_at.asc())
    )
    notes_rows = list(notes_result.scalars().all())
    notes_out = [await _serialize_note(db, n) for n in notes_rows]
    fb_result = await db.execute(
        select(EventFeedback)
        .where(EventFeedback.event_id == event_id)
        .order_by(EventFeedback.created_at.asc())
    )
    base = EventResponse.model_validate(event).model_dump()
    base["notes"] = notes_out
    base["feedback"] = [await _serialize_feedback(db, fb) for fb in fb_result.scalars().all()]
    return base


# ── Phase 4. Event notes (annotations) ──

@router.get("/{event_id}/notes", response_model=list[EventNoteResponse])
async def list_event_notes(
    event_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    result = await db.execute(
        select(EventNote)
        .where(EventNote.event_id == event_id)
        .order_by(EventNote.created_at.asc())
    )
    return [await _serialize_note(db, n) for n in result.scalars().all()]


@router.post("/{event_id}/notes", response_model=EventNoteResponse, status_code=201)
async def create_event_note(
    event_id: uuid.UUID,
    body: EventNoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach a free-text annotation to an event. Source defaults to
    ``web`` since this endpoint backs the timeline's "+ Add note" UI.
    Telegram replies create their own rows via the poller path."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Note text cannot be empty")
    note = EventNote(
        event_id=event_id,
        author_user_id=current_user.id,
        source="web",
        text=text[:4096],
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return await _serialize_note(db, note)


@router.delete("/{event_id}/notes/{note_id}", status_code=204)
async def delete_event_note(
    event_id: uuid.UUID,
    note_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete an event note. Author or admin only.

    We picked hard delete over soft delete because notes are cheap and
    a half-empty row in the timeline would just confuse users. Audit
    history lives on the Event itself.
    """
    note = await db.get(EventNote, note_id)
    if note is None or note.event_id != event_id:
        raise HTTPException(status_code=404, detail="Note not found")
    is_admin = (getattr(current_user, "role", "") or "").lower() == "admin"
    if note.author_user_id != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Only the author or an admin can delete this note")
    await db.delete(note)
    await db.commit()


@router.post("/{event_id}/acknowledge", response_model=EventResponse)
async def acknowledge_event(
    event_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(event)
    return event


@router.post("/{event_id}/ack", response_model=EventResponse)
async def ack_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Phase 2 ack endpoint. Symmetric counterpart to the Telegram
    inline-button ack. Any authenticated user can ack their own
    household's events; the ack records the acting user so the
    timeline can show "Acknowledged by Aisha (web)" regardless of
    whether the ack arrived via the Telegram button or the web UI.

    Idempotent. a second ack on an already-acknowledged event is a
    no-op that returns the existing record (the first acker is
    preserved). Mirrors the prior ``acknowledged_at`` column so old
    dashboards keep working.
    """
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.acked_at is None:
        now = datetime.now(timezone.utc)
        event.acked_at = now
        event.acked_by_user_id = current_user.id
        event.acked_via = "web"
        # Mirror to the legacy column so callers reading either field
        # see the ack. Phase 1 dashboards only read acknowledged_at.
        if event.acknowledged_at is None:
            event.acknowledged_at = now
        await db.commit()
        await db.refresh(event)
    return event


@router.post("/{event_id}/mute", response_model=EventResponse)
async def mute_event(
    event_id: uuid.UUID,
    duration_seconds: int = Query(default=600, ge=60, le=86400),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Web counterpart to the Telegram 🔕 button. Sets ``muted_until`` so
    notification channels skip re-sends for this event for the duration
    (default 10 minutes, same as Telegram)."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event.muted_until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
    await db.commit()
    await db.refresh(event)
    return event
