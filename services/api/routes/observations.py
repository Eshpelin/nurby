import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import get_current_user, require_query_token
from shared.camera_access import allowed_camera_ids, apply_camera_filter
from shared.config import settings
from shared.database import get_db
from shared.models import Camera, Observation, ObservationVlmPass, Person, User
from shared.paths import escape_like, resolve_inside
from shared.schemas import ObservationResponse

router = APIRouter()


@router.get("/{observation_id}/vlm-passes")
async def get_vlm_passes(
    observation_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ordered version history of every VLM pass over this frame.

    Pass 1 is the original live caption. later passes are idle enrichment.
    The pass with ``authoritative=true`` is the one currently surfaced as
    the observation's caption.
    """
    obs = await db.get(Observation, observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    rows = (await db.execute(
        select(ObservationVlmPass)
        .where(ObservationVlmPass.observation_id == observation_id)
        .order_by(ObservationVlmPass.pass_no.asc())
    )).scalars().all()
    return [
        {
            "pass_no": p.pass_no,
            "lens": p.lens,
            "prompt_version": p.prompt_version,
            "provider_name": p.provider_name,
            "model": p.model,
            "description": p.description,
            "attributes": p.attributes,
            "confidence": p.confidence,
            "authoritative": p.authoritative,
            "superseded": p.superseded,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.get("", response_model=list[ObservationResponse])
async def list_observations(
    camera_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from", description="Inclusive start (ISO 8601)"),
    to: datetime | None = Query(default=None, description="Inclusive end (ISO 8601)"),
    person_id: uuid.UUID | None = Query(default=None, description="Filter to observations naming this person"),
    label: str | None = Query(default=None, description="Filter to observations with this YOLO label"),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    allowed = await allowed_camera_ids(current_user, db)
    query = apply_camera_filter(
        select(Observation).order_by(Observation.started_at.desc()),
        allowed,
        Observation.camera_id,
    )
    # Drop observations from cameras hidden from the review feed (they keep
    # recording; this list is a review surface).
    query = query.where(
        Observation.camera_id.not_in(
            select(Camera.id).where(Camera.exclude_from_review.is_(True))
        )
    )
    if camera_id:
        query = query.where(Observation.camera_id == camera_id)
    if from_:
        query = query.where(Observation.started_at >= from_)
    if to:
        query = query.where(Observation.started_at <= to)
    if person_id:
        # person_detections stores the canonical display_name. Resolve
        # the id to a name and match the JSON text.
        name = (
            await db.execute(select(Person.display_name).where(Person.id == person_id))
        ).scalars().first()
        if not name:
            return []
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
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{observation_id}", response_model=ObservationResponse)
async def get_observation(observation_id: uuid.UUID, _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    observation = await db.get(Observation, observation_id)
    if not observation:
        raise HTTPException(status_code=404, detail="Observation not found")
    return observation


@router.get("/{observation_id}/thumbnail")
async def get_observation_thumbnail(
    observation_id: uuid.UUID,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Thumbnail auth accepts either Bearer header or a `?token=` query
    param so <img> tags can load without JS."""
    require_query_token(token)
    observation = await db.get(Observation, observation_id)
    if not observation:
        raise HTTPException(status_code=404, detail="Observation not found")
    if not observation.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    path = resolve_inside(observation.thumbnail_path, settings.thumbnails_path)
    if path is None:
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found on disk")
    return FileResponse(path, media_type="image/jpeg")
