"""Transcripts API.

Phase 1 endpoints. Read, search, export, delete. The PATCH path that
edits a transcript writes ``original_text`` once on first edit so the
audit story stays intact.

Speaker attribution (#227) rides on the transcript row as overlay
metadata. The write path fills it from face co-presence (Tier A, see
``services/perception/audio/speaker_video.py``); this API surfaces the
attributed name and lets a household correct it. A correction is stored
as ``speaker_source == 'manual'`` and audited in ``AudioAuditLog`` the
same way camera audio toggles are, so re-summarize / re-interpret flows
(which only rewrite the conversation summary) never destroy it.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.camera_access import allowed_camera_ids, apply_camera_filter, require_camera_in_scope
from shared.database import get_db
from shared.models import AudioAuditLog, Person, Transcript, User
from shared.paths import escape_like

router = APIRouter()


class TranscriptResponse(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    audio_capture_id: uuid.UUID | None
    started_at: datetime
    ended_at: datetime
    text: str
    original_text: str | None
    text_edited: bool
    language: str | None
    provider: str
    model: str
    confidence: float | None
    no_speech_prob: float | None
    filtered: bool
    # Speaker attribution overlay (#227). ``speaker_name`` is resolved
    # from the person row so a client renders a label without fetching
    # the whole household. ``speaker_source`` is video | voice | fused |
    # manual | ambiguous; only a confidently attributed line carries a
    # name, ambiguous lines stay unattributed rather than guessed.
    speaker_person_id: uuid.UUID | None = None
    speaker_source: str | None = None
    speaker_confidence: float | None = None
    speaker_name: str | None = None

    class Config:
        from_attributes = True


class TranscriptUpdate(BaseModel):
    text: str


class TranscriptSpeakerUpdate(BaseModel):
    # ``None`` clears the attribution back to unattributed. A UUID sets
    # (or corrects) the speaker to a known person.
    speaker_person_id: uuid.UUID | None = None


async def _speaker_names(
    db: AsyncSession, rows: list[Transcript]
) -> dict[uuid.UUID, str]:
    """Batch-resolve display names for the attributed speakers in
    ``rows``. Nickname wins wherever a household reads a name, matching
    the conversations API."""
    person_ids = {t.speaker_person_id for t in rows if t.speaker_person_id}
    if not person_ids:
        return {}
    people = (
        await db.execute(select(Person).where(Person.id.in_(person_ids)))
    ).scalars().all()
    return {p.id: (p.nickname or p.display_name) for p in people}


def _to_response(t: Transcript, names: dict[uuid.UUID, str]) -> TranscriptResponse:
    return TranscriptResponse(
        id=t.id,
        camera_id=t.camera_id,
        audio_capture_id=t.audio_capture_id,
        started_at=t.started_at,
        ended_at=t.ended_at,
        text=t.text,
        original_text=t.original_text,
        text_edited=t.text_edited,
        language=t.language,
        provider=t.provider,
        model=t.model,
        confidence=t.confidence,
        no_speech_prob=t.no_speech_prob,
        filtered=t.filtered,
        speaker_person_id=t.speaker_person_id,
        speaker_source=t.speaker_source,
        speaker_confidence=t.speaker_confidence,
        speaker_name=names.get(t.speaker_person_id) if t.speaker_person_id else None,
    )


@router.get("", response_model=list[TranscriptResponse])
async def list_transcripts(
    camera_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    include_filtered: bool = Query(default=False),
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(_user, db)
    query = apply_camera_filter(select(Transcript), allowed, Transcript.camera_id).order_by(Transcript.started_at.desc())
    clauses = []
    if camera_id:
        clauses.append(Transcript.camera_id == camera_id)
    if from_:
        clauses.append(Transcript.started_at >= from_)
    if to:
        clauses.append(Transcript.started_at <= to)
    if search:
        clauses.append(Transcript.text.ilike(f"%{escape_like(search)}%", escape="\\"))
    if not include_filtered:
        clauses.append(Transcript.filtered.is_(False))
    if clauses:
        query = query.where(and_(*clauses))
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.scalars().all()
    names = await _speaker_names(db, rows)
    return [_to_response(t, names) for t in rows]


@router.get("/export.csv")
async def export_transcripts_csv(
    camera_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR-friendly export. CSV stream so multi-million-row exports
    do not blow the API server memory."""
    allowed = await allowed_camera_ids(_user, db)
    query = apply_camera_filter(select(Transcript), allowed, Transcript.camera_id).order_by(Transcript.started_at.asc())
    clauses = [Transcript.filtered.is_(False)]
    if camera_id:
        clauses.append(Transcript.camera_id == camera_id)
    if from_:
        clauses.append(Transcript.started_at >= from_)
    if to:
        clauses.append(Transcript.started_at <= to)
    query = query.where(and_(*clauses))

    def _generator():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "camera_id",
                "started_at",
                "ended_at",
                "duration_ms",
                "language",
                "provider",
                "model",
                "text",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()

    async def _stream():
        # Header.
        head = io.StringIO()
        writer = csv.writer(head)
        writer.writerow(
            ["id", "camera_id", "started_at", "ended_at", "duration_ms", "language", "provider", "model", "text"]
        )
        yield head.getvalue()

        result = await db.stream(query)
        async for row in result.scalars():
            row_buf = io.StringIO()
            csv.writer(row_buf).writerow(
                [
                    str(row.id),
                    str(row.camera_id),
                    row.started_at.isoformat(),
                    row.ended_at.isoformat(),
                    int((row.ended_at - row.started_at).total_seconds() * 1000),
                    row.language or "",
                    row.provider,
                    row.model,
                    row.text,
                ]
            )
            yield row_buf.getvalue()

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="transcripts.csv"'},
    )


@router.get("/{transcript_id}", response_model=TranscriptResponse)
async def get_transcript(
    transcript_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    await require_camera_in_scope(_user, db, t.camera_id, detail="Transcript not found")
    names = await _speaker_names(db, [t])
    return _to_response(t, names)


@router.patch("/{transcript_id}", response_model=TranscriptResponse)
async def update_transcript(
    transcript_id: uuid.UUID,
    body: TranscriptUpdate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    await require_camera_in_scope(_user, db, t.camera_id, detail="Transcript not found")
    if not t.text_edited:
        # Snapshot the original on the first edit only.
        t.original_text = t.text
        t.text_edited = True
    t.text = body.text
    await db.commit()
    await db.refresh(t)
    names = await _speaker_names(db, [t])
    return _to_response(t, names)


@router.patch("/{transcript_id}/speaker", response_model=TranscriptResponse)
async def set_transcript_speaker(
    transcript_id: uuid.UUID,
    body: TranscriptSpeakerUpdate,
    request: Request,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Correct (or clear) the attributed speaker on a transcript line.

    The heuristic write-path attribution (face co-presence) is a
    best-effort guess; this is the household's correction affordance,
    consistent with the transcript text edit (#176). A correction is a
    manual override: ``speaker_source`` becomes ``manual`` with full
    confidence, or the line is returned to unattributed when the person
    is cleared. Every change is written to ``AudioAuditLog`` so
    attribution edits are auditable like the rest of the audio subsystem.

    Attribution lives on the transcript row, so re-summarize /
    re-interpret flows (which only rewrite the conversation summary)
    leave a correction untouched.
    """
    t = await db.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    await require_camera_in_scope(_user, db, t.camera_id, detail="Transcript not found")

    person: Person | None = None
    if body.speaker_person_id is not None:
        person = await db.get(Person, body.speaker_person_id)
        if person is None:
            raise HTTPException(status_code=404, detail="Person not found")

    old_id = str(t.speaker_person_id) if t.speaker_person_id else None
    new_id = str(body.speaker_person_id) if body.speaker_person_id else None
    if old_id != new_id:
        t.speaker_person_id = body.speaker_person_id
        if body.speaker_person_id is not None:
            t.speaker_source = "manual"
            t.speaker_confidence = 1.0
        else:
            t.speaker_source = None
            t.speaker_confidence = None
        db.add(
            AudioAuditLog(
                camera_id=t.camera_id,
                user_id=_user.id,
                field="transcript_speaker",
                old_value=old_id,
                new_value=new_id,
                ip=request.client.host if request.client else None,
            )
        )
        await db.commit()
        await db.refresh(t)

    names = await _speaker_names(db, [t])
    return _to_response(t, names)


@router.delete("/{transcript_id}", status_code=204)
async def delete_transcript(
    transcript_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    await require_camera_in_scope(_user, db, t.camera_id, detail="Transcript not found")
    await db.delete(t)
    await db.commit()


@router.delete("/by-camera/{camera_id}")
async def bulk_delete_for_camera(
    camera_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_camera_in_scope(_user, db, camera_id, detail="Camera not found")
    result = await db.execute(
        select(Transcript).where(Transcript.camera_id == camera_id)
    )
    rows = result.scalars().all()
    for r in rows:
        await db.delete(r)
    await db.commit()
    return {"deleted": len(rows)}
