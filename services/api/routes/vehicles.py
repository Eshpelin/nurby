"""Vehicle identities API. the vehicle analogue of persons.py.

Vehicles are auto-created by the perception pipeline (keyed by license
plate). Sightings are not a separate table. they are read out of
``Observation.vehicle_detections`` exactly like People reads
person_detections, so a vehicle's "where + when" comes straight from the
timeline data already being stored.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.associator import evidence_balance
from shared.auth import get_current_user, require_admin, require_query_token
from shared.camera_access import ALL, allowed_camera_ids, apply_camera_filter
from shared.config import settings
from shared.database import get_db
from shared.models import (
    AssociationEvidence,
    AssociationReviewEvent,
    Camera,
    EntityAssociation,
    Observation,
    User,
    Vehicle,
)
from shared.paths import resolve_inside

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _camera_set_is_scoped(camera_ids, allowed) -> bool:
    """Return whether every affected camera is visible to the caller."""
    if allowed is ALL:
        return True
    visible = {str(camera_id) for camera_id in (allowed or set())}
    return {str(camera_id) for camera_id in camera_ids if camera_id} <= visible


class VehicleResponse(BaseModel):
    id: uuid.UUID
    identity_key: str
    display_name: str
    nickname: str | None = None
    license_plate: str | None = None
    vehicle_type: str | None = None
    make: str | None = None
    model: str | None = None
    color: str | None = None
    description: str | None = None
    description_status: str = "pending"
    is_starred: bool = False
    is_provisional: bool = True
    sighting_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    first_camera_id: uuid.UUID | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class VehicleUpdate(BaseModel):
    display_name: str | None = None
    nickname: str | None = None
    license_plate: str | None = None
    vehicle_type: str | None = None
    make: str | None = None
    model: str | None = None
    color: str | None = None
    is_starred: bool | None = None


class VehicleMerge(BaseModel):
    """Explicit operator reconciliation of two auto-created vehicle rows."""

    source_id: uuid.UUID
    note: str | None = None


def _rewrite_vehicle_detection_ids(value, source_id: str, target_id: str, target_key: str):
    """Rewrite only persisted vehicle identity fields in observation JSON.

    Detection metadata and timestamps are deliberately left untouched. This
    makes a merge reversible at the evidence level and avoids changing what
    the detector originally saw.
    """
    if not isinstance(value, dict):
        return value
    vehicles = value.get("vehicles")
    if not isinstance(vehicles, list):
        return value
    rewritten = dict(value)
    rewritten["vehicles"] = [
        {
            **entry,
            "vehicle_id": target_id if str(entry.get("vehicle_id")) == source_id else entry.get("vehicle_id"),
            "identity_key": target_key if str(entry.get("vehicle_id")) == source_id else entry.get("identity_key"),
        }
        for entry in vehicles
        if isinstance(entry, dict)
    ]
    return rewritten


def _merge_histogram(left: dict | None, right: dict | None) -> dict:
    merged = {str(k): int(v or 0) for k, v in (left or {}).items()}
    for key, value in (right or {}).items():
        merged[str(key)] = merged.get(str(key), 0) + int(value or 0)
    return merged


def _plate_correction_metadata(vehicle_id: uuid.UUID, old_plate: str | None, new_plate: str | None) -> dict:
    """Describe a human plate correction without rewriting old observations."""
    return {
        "policy": "human_plate_correction",
        "vehicle_id": str(vehicle_id),
        "previous_plate": old_plate,
        "corrected_plate": new_plate,
        "historical_evidence_preserved": True,
    }


def _vehicle_ids_in(obs: Observation) -> set[str]:
    vd = obs.vehicle_detections or {}
    out: set[str] = set()
    for v in vd.get("vehicles", []) or []:
        vid = v.get("vehicle_id")
        if vid:
            out.add(str(vid))
    return out


async def _vehicle_in_scope(
    vehicle: Vehicle, user: User, db: AsyncSession, allowed=None,
) -> bool:
    """Authorize identity operations using visible evidence, not only first sighting."""
    allowed = await allowed_camera_ids(user, db) if allowed is None else allowed
    if allowed is ALL or vehicle.first_camera_id in allowed:
        return True
    visible_obs = (
        await db.execute(
            apply_camera_filter(
                select(Observation).where(Observation.vehicle_detections.is_not(None)),
                allowed,
                Observation.camera_id,
            )
        )
    ).scalars().all()
    target = str(vehicle.id)
    return any(target in _vehicle_ids_in(observation) for observation in visible_obs)


@router.get("", response_model=list[VehicleResponse])
async def list_vehicles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All known vehicles, most recently seen first."""
    allowed = await allowed_camera_ids(current_user, db)
    stmt = select(Vehicle)
    if allowed is not ALL:
        stmt = stmt.where(Vehicle.first_camera_id.in_(allowed))
    rows = (await db.execute(stmt.order_by(Vehicle.last_seen_at.desc()))).scalars().all()
    return rows


@router.get("/activity/summary")
async def vehicles_activity_summary(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-vehicle sighting counts (1h / 24h / total) + last camera.

    Scans observations from the last 7 days and tallies by vehicle_id,
    mirroring the People activity summary.
    """
    allowed = await allowed_camera_ids(_current_user, db)
    vehicle_stmt = select(Vehicle)
    if allowed is not ALL:
        vehicle_stmt = vehicle_stmt.where(Vehicle.first_camera_id.in_(allowed))
    vehicles = (await db.execute(vehicle_stmt)).scalars().all()
    if not vehicles:
        return []

    cam_rows = (await db.execute(select(Camera.id, Camera.name))).all()
    cam_names = {str(cid): name for cid, name in cam_rows}

    now = _now()
    cutoff_7d = now - timedelta(days=7)
    obs = (
        await db.execute(
            apply_camera_filter(
                select(Observation).where(
                    Observation.vehicle_detections.is_not(None),
                    Observation.started_at >= cutoff_7d,
                ),
                allowed,
                Observation.camera_id,
            ).order_by(Observation.started_at.desc())
        )
    ).scalars().all()

    cutoff_1h = now - timedelta(hours=1)
    cutoff_24h = now - timedelta(hours=24)

    agg: dict[str, dict] = {}
    for o in obs:
        ts = o.started_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        for vid in _vehicle_ids_in(o):
            a = agg.setdefault(vid, {"total": 0, "h1": 0, "h24": 0, "last": None, "last_cam": None})
            a["total"] += 1
            if ts >= cutoff_1h:
                a["h1"] += 1
            if ts >= cutoff_24h:
                a["h24"] += 1
            if a["last"] is None or ts > a["last"]:
                a["last"] = ts
                a["last_cam"] = cam_names.get(str(o.camera_id))

    out = []
    for v in vehicles:
        a = agg.get(str(v.id), {})
        out.append({
            "vehicle_id": str(v.id),
            "display_name": v.display_name,
            "license_plate": v.license_plate,
            "vehicle_type": v.vehicle_type,
            "color": v.color,
            "make": v.make,
            "model": v.model,
            "description": v.description,
            "is_starred": v.is_starred,
            "total_sightings": a.get("total", v.sighting_count or 0),
            "sightings_1h": a.get("h1", 0),
            "sightings_24h": a.get("h24", 0),
            "last_seen_at": (a.get("last") or v.last_seen_at),
            "last_seen_camera": a.get("last_cam"),
            "first_seen_at": v.first_seen_at,
        })
    return out


@router.get("/activity/{vehicle_id}")
async def vehicle_activity_feed(
    vehicle_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sightings of one vehicle. observations whose vehicle_detections
    reference this vehicle, newest first, with camera name + thumbnail."""
    allowed = await allowed_camera_ids(_current_user, db)
    cam_rows = (await db.execute(select(Camera.id, Camera.name))).all()
    cam_names = {str(cid): name for cid, name in cam_rows}

    obs = (
        await db.execute(
            apply_camera_filter(
                select(Observation).where(Observation.vehicle_detections.is_not(None)),
                allowed,
                Observation.camera_id,
            )
            .order_by(Observation.started_at.desc())
            .limit(limit * 6)
        )
    ).scalars().all()

    target = str(vehicle_id)
    feed = []
    for o in obs:
        if target not in _vehicle_ids_in(o):
            continue
        plate = None
        for v in (o.vehicle_detections or {}).get("vehicles", []) or []:
            if str(v.get("vehicle_id")) == target:
                plate = v.get("plate_text")
                break
        feed.append({
            "observation_id": str(o.id),
            "camera_id": str(o.camera_id),
            "camera_name": cam_names.get(str(o.camera_id)),
            "started_at": o.started_at,
            "vlm_description": o.vlm_description,
            "thumbnail_path": o.thumbnail_path,
            "plate_text": plate,
        })
        if len(feed) >= limit:
            break
    return feed


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    v = await db.get(Vehicle, vehicle_id)
    if v is None or not await _vehicle_in_scope(v, _current_user, db):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return v


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    body: VehicleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    v = await db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    if not await _vehicle_in_scope(v, current_user, db):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    data = body.model_dump(exclude_unset=True)
    old_plate = v.license_plate
    plate_changed = "license_plate" in data and data["license_plate"] != old_plate
    for field, value in data.items():
        setattr(v, field, value)
    # A human edited it. no longer a provisional auto-guess.
    if any(k in data for k in ("display_name", "make", "model", "license_plate")):
        v.is_provisional = False
    if plate_changed:
        now = _now()
        associations = (
            await db.execute(
                select(EntityAssociation)
                .where(EntityAssociation.object_kind == "vehicle")
                .where(EntityAssociation.object_key == str(vehicle_id))
                .where(EntityAssociation.source == "learned")
                .where(EntityAssociation.status != "rejected")
            )
        ).scalars().all()
        for association in associations:
            db.add(AssociationEvidence(
                association_id=association.id,
                episode_key=f"plate-correction:{vehicle_id}:{now.isoformat()}",
                evidence_kind="vehicle_plate_correction",
                role="contradictory",
                observed_at=now,
                camera_ids=list((association.camera_histogram or {}).keys()),
                explanation="A human corrected the vehicle plate; historical reads remain unchanged and the learned association needs review.",
                evidence_metadata=_plate_correction_metadata(vehicle_id, old_plate, data["license_plate"]),
            ))
            association.contradictory_evidence_count = int(
                getattr(association, "contradictory_evidence_count", 0) or 0
            ) + 1
            association.confidence_score, association.decision_explanation = evidence_balance(
                int(getattr(association, "supporting_evidence_count", association.evidence_count) or 0),
                association.contradictory_evidence_count,
            )
            old_status = association.status
            if not association.user_confirmed and association.status == "established":
                association.status = "ambiguous"
            db.add(AssociationReviewEvent(
                association_id=association.id,
                reviewer_user_id=current_user.id,
                action="contradiction",
                old_status=old_status,
                new_status=association.status,
                note="Vehicle plate corrected by a user; review the learned association evidence.",
            ))
    await db.commit()
    await db.refresh(v)
    return v


@router.post("/{target_id}/merge", response_model=VehicleResponse)
async def merge_vehicle(
    target_id: uuid.UUID,
    body: VehicleMerge,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Merge a duplicate vehicle identity without discarding its evidence.

    This is intentionally an explicit admin action. It rewrites historical
    observation references to the surviving vehicle, folds duplicate learned
    association evidence into the survivor, and records the original source
    association in the evidence metadata. It never infers ownership.
    """
    if body.source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a vehicle into itself")
    target = await db.get(Vehicle, target_id)
    source = await db.get(Vehicle, body.source_id)
    if target is None or source is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    allowed = await allowed_camera_ids(_current_user, db)

    source_id = str(body.source_id)
    target_id_text = str(target_id)
    observations = (
        await db.execute(select(Observation).where(Observation.vehicle_detections.is_not(None)))
    ).scalars().all()
    impacted_observations = []
    for observation in observations:
        rewritten = _rewrite_vehicle_detection_ids(
            observation.vehicle_detections or {}, source_id, target_id_text, target.identity_key
        )
        if rewritten != (observation.vehicle_detections or {}):
            impacted_observations.append(observation)

    # Merging rewrites historical observations and association evidence. A
    # selected-camera administrator must not mutate rows whose provenance is
    # outside their grant, even though the operation itself is admin-only.
    impacted_camera_ids = {observation.camera_id for observation in impacted_observations}
    all_vehicle_edges = (
        await db.execute(
            select(EntityAssociation)
            .where(EntityAssociation.object_kind == "vehicle")
            .where(EntityAssociation.object_key.in_([source_id, target_id_text]))
        )
    ).scalars().all()
    for edge in all_vehicle_edges:
        impacted_camera_ids.update((edge.camera_histogram or {}).keys())
    if not _camera_set_is_scoped(impacted_camera_ids, allowed):
        raise HTTPException(status_code=404, detail="Vehicle not found")

    rewritten_count = 0
    for observation in impacted_observations:
        detections = observation.vehicle_detections or {}
        rewritten = _rewrite_vehicle_detection_ids(
            detections, source_id, target_id_text, target.identity_key
        )
        if rewritten != detections:
            observation.vehicle_detections = rewritten
            rewritten_count += 1

    source_edges = [edge for edge in all_vehicle_edges if edge.object_key == source_id]
    for source_edge in source_edges:
        target_edge = (
            await db.execute(
                select(EntityAssociation)
                .where(EntityAssociation.subject_kind == source_edge.subject_kind)
                .where(EntityAssociation.subject_key == source_edge.subject_key)
                .where(EntityAssociation.object_kind == "vehicle")
                .where(EntityAssociation.object_key == target_id_text)
                .where(EntityAssociation.relation == source_edge.relation)
                .where(EntityAssociation.source == source_edge.source)
            )
        ).scalar_one_or_none()
        if target_edge is None:
            source_edge.object_key = target_id_text
            source_edge.object_label = target.display_name
            continue

        evidence = (
            await db.execute(
                select(AssociationEvidence).where(AssociationEvidence.association_id == source_edge.id)
            )
        ).scalars().all()
        for row in evidence:
            row.association_id = target_edge.id
            row.episode_key = f"merge:{source_id}:{row.episode_key}"[:255]
            metadata = dict(row.evidence_metadata or {})
            metadata["reconciled_from_vehicle_id"] = source_id
            row.evidence_metadata = metadata
        events = (
            await db.execute(
                select(AssociationReviewEvent).where(AssociationReviewEvent.association_id == source_edge.id)
            )
        ).scalars().all()
        for event in events:
            event.association_id = target_edge.id
        target_edge.evidence_count += source_edge.evidence_count
        target_edge.supporting_evidence_count += source_edge.supporting_evidence_count
        target_edge.contradictory_evidence_count += source_edge.contradictory_evidence_count
        target_edge.distinct_days = max(target_edge.distinct_days, source_edge.distinct_days)
        target_edge.hour_histogram = _merge_histogram(target_edge.hour_histogram, source_edge.hour_histogram)
        target_edge.dow_histogram = _merge_histogram(target_edge.dow_histogram, source_edge.dow_histogram)
        target_edge.camera_histogram = _merge_histogram(target_edge.camera_histogram, source_edge.camera_histogram)
        target_edge.first_seen_at = min(filter(None, (target_edge.first_seen_at, source_edge.first_seen_at)), default=None)
        target_edge.last_seen_at = max(filter(None, (target_edge.last_seen_at, source_edge.last_seen_at)), default=None)
        await db.delete(source_edge)

    target.sighting_count = (target.sighting_count or 0) + (source.sighting_count or 0)
    target.first_seen_at = min(filter(None, (target.first_seen_at, source.first_seen_at)), default=None)
    target.last_seen_at = max(filter(None, (target.last_seen_at, source.last_seen_at)), default=None)
    if not target.photo_path and source.photo_path:
        target.photo_path = source.photo_path
    target.is_provisional = target.is_provisional and source.is_provisional
    await db.delete(source)
    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/{vehicle_id}", status_code=204)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    v = await db.get(Vehicle, vehicle_id)
    if v is None or not await _vehicle_in_scope(v, _current_user, db):
        raise HTTPException(status_code=404, detail="Vehicle not found")
    await db.delete(v)
    await db.commit()
    return None


@router.get("/{vehicle_id}/photo")
async def vehicle_photo(
    vehicle_id: uuid.UUID,
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Best available photo. the vehicle's stored photo, else the most
    recent sighting thumbnail. Accepts a token query param so <img> tags
    work without a header."""
    user_id = require_query_token(token)
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    allowed = await allowed_camera_ids(user, db)

    v = await db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    if allowed is not ALL and v.first_camera_id not in allowed:
        # A vehicle's first sighting may be outside the current grant, but a
        # later authorized observation can still make the identity visible.
        visible_obs = (
            await db.execute(
                apply_camera_filter(
                    select(Observation)
                    .where(Observation.vehicle_detections.is_not(None)),
                    allowed,
                    Observation.camera_id,
                )
            )
        ).scalars().all()
        if not any(str(vehicle_id) in _vehicle_ids_in(o) for o in visible_obs):
            raise HTTPException(status_code=404, detail="Vehicle not found")

    path = v.photo_path
    if not path or not os.path.exists(path):
        # Fall back to the latest sighting thumbnail.
        obs = (
            await db.execute(
                apply_camera_filter(
                    select(Observation)
                    .where(Observation.vehicle_detections.is_not(None)),
                    allowed,
                    Observation.camera_id,
                )
                .order_by(Observation.started_at.desc())
                .limit(200)
            )
        ).scalars().all()
        target = str(vehicle_id)
        for o in obs:
            if target in _vehicle_ids_in(o) and o.thumbnail_path and os.path.exists(o.thumbnail_path):
                path = o.thumbnail_path
                break
    path = resolve_inside(path, settings.thumbnails_path)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No photo available")
    return FileResponse(path, media_type="image/jpeg")
