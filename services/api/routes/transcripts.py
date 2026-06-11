"""Transcripts API.

Phase 1 endpoints. Read, search, export, delete. The PATCH path that
edits a transcript writes ``original_text`` once on first edit so the
audit story stays intact.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user
from shared.database import get_db
from shared.models import Transcript, User
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

    class Config:
        from_attributes = True


class TranscriptUpdate(BaseModel):
    text: str


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
    query = select(Transcript).order_by(Transcript.started_at.desc())
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
    return result.scalars().all()


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
    query = select(Transcript).order_by(Transcript.started_at.asc())
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
    return t


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
    if not t.text_edited:
        # Snapshot the original on the first edit only.
        t.original_text = t.text
        t.text_edited = True
    t.text = body.text
    await db.commit()
    await db.refresh(t)
    return t


@router.delete("/{transcript_id}", status_code=204)
async def delete_transcript(
    transcript_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    await db.delete(t)
    await db.commit()


@router.delete("/by-camera/{camera_id}")
async def bulk_delete_for_camera(
    camera_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transcript).where(Transcript.camera_id == camera_id)
    )
    rows = result.scalars().all()
    for r in rows:
        await db.delete(r)
    await db.commit()
    return {"deleted": len(rows)}
