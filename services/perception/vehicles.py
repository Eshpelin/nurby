"""Vehicle identity. the vehicle analogue of faces.py.

A vehicle is identified by its license plate when one is read (exact), so
the same car seen across frames and cameras collapses to one Vehicle row.
Every vehicle detection in a frame is recorded in
``Observation.vehicle_detections`` (mirrors person_detections) so the
Vehicles tab can query sightings the same way People does.

Plateless vehicles (e.g. forklifts, or a car at a bad angle) are
re-identified by their CLIP appearance embedding. a recurring plateless
vehicle on the same camera within a recent window collapses to one
provisional Vehicle row instead of getting no identity at all. The match
threshold is deliberately tight and scoped to the same camera, because
CLIP captures coarse appearance. it groups a distinctive recurring
vehicle well but would over-merge a street full of identical sedans, so
plateless identities are always provisional for a human to confirm or
split. A dedicated vehicle re-id model would sharpen this later.

A short VLM description ("Red Nissan sedan, tinted windows") is generated
once per new vehicle in the background so it never blocks the keyframe
path or re-runs every frame.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from sqlalchemy import select

from shared.database import async_session
from shared.models import Vehicle

logger = logging.getLogger("nurby.perception.vehicles")

VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "van"}

_VEHICLE_SYSTEM_PROMPT = (
    "You are describing a single vehicle crop from a security camera. "
    "Reply with ONE short line. color, make and model if visible, body "
    "type, and any notable feature (tinted windows, roof rack, damage, "
    "livery). Example. 'Red Nissan sedan with tinted windows'. If unsure "
    "of make or model, omit them. Do not mention the background."
)


def _norm_plate(text: str | None) -> str | None:
    """Uppercase, strip non-alphanumerics. None if too short to trust."""
    if not text:
        return None
    cleaned = "".join(ch for ch in text.upper() if ch.isalnum())
    return cleaned if len(cleaned) >= 3 else None


def _bbox_center_inside(plate_bbox: list, vehicle_bbox: list) -> bool:
    """True if the plate box's center sits inside the vehicle box."""
    try:
        px = (plate_bbox[0] + plate_bbox[2]) / 2
        py = (plate_bbox[1] + plate_bbox[3]) / 2
        return (
            vehicle_bbox[0] <= px <= vehicle_bbox[2]
            and vehicle_bbox[1] <= py <= vehicle_bbox[3]
        )
    except (IndexError, TypeError):
        return False


# Plateless appearance re-id tuning. Tight so we under-merge rather than
# collapse distinct vehicles. Same camera, recent, high CLIP similarity.
_PLATELESS_MAX_DISTANCE = 0.12   # cosine distance. ~0.88 similarity
_PLATELESS_RECENCY_HOURS = 24


async def identify_vehicles(db, camera_id, detections: list, ts, frame=None) -> tuple[dict | None, list]:
    """Build vehicle_detections and upsert Vehicle rows.

    Plated vehicles key on the exact plate. Plateless vehicles re-identify by
    CLIP appearance against recent same-camera plateless rows (needs ``frame``).
    Returns (vehicle_detections, new_vehicle_jobs) where new_vehicle_jobs is a
    list of (vehicle_id, bbox) for vehicles that still need a description.
    Runs inside the caller's db session/transaction.
    """
    if not detections:
        return None, []

    vehicles = [d for d in detections if d.get("label") in VEHICLE_LABELS]
    if not vehicles:
        return None, []
    plates = [d for d in detections if d.get("label") == "license_plate" and d.get("plate_text")]

    entries: list[dict] = []
    new_jobs: list = []

    for v in vehicles:
        vbox = v.get("bbox") or []
        # Find a plate whose center falls inside this vehicle box.
        plate_text = None
        for p in plates:
            if _bbox_center_inside(p.get("bbox") or [], vbox):
                plate_text = _norm_plate(p.get("plate_text"))
                break
        plate_text = plate_text or _norm_plate(v.get("plate_text"))

        entry = {
            "bbox": vbox,
            "label": v.get("label"),
            "confidence": v.get("confidence"),
            "plate_text": plate_text,
            "vehicle_id": None,
            "identity_key": None,
        }

        if plate_text:
            identity_key = plate_text  # plate is the exact identity
            vehicle = (
                await db.execute(select(Vehicle).where(Vehicle.identity_key == identity_key))
            ).scalar_one_or_none()
            if vehicle is None:
                vehicle = Vehicle(
                    identity_key=identity_key,
                    display_name=f"Plate {plate_text}",
                    license_plate=plate_text,
                    vehicle_type=v.get("label"),
                    first_camera_id=camera_id,
                    first_seen_at=ts,
                    last_seen_at=ts,
                    sighting_count=1,
                    is_provisional=True,
                    description_status="pending",
                )
                db.add(vehicle)
                await db.flush()  # get id
                new_jobs.append((vehicle.id, vbox))
            else:
                vehicle.last_seen_at = ts
                vehicle.sighting_count = (vehicle.sighting_count or 0) + 1
                if not vehicle.vehicle_type:
                    vehicle.vehicle_type = v.get("label")
                if vehicle.description_status == "pending" and not vehicle.description:
                    new_jobs.append((vehicle.id, vbox))
            entry["vehicle_id"] = str(vehicle.id)
            entry["identity_key"] = identity_key
        elif frame is not None:
            # Plateless. re-identify by CLIP appearance against recent
            # same-camera plateless rows.
            vid, ikey, job = await _identify_plateless(db, camera_id, v, vbox, ts, frame)
            if vid is not None:
                entry["vehicle_id"] = str(vid)
                entry["identity_key"] = ikey
                if job is not None:
                    new_jobs.append(job)

        entries.append(entry)

    vehicle_detections = {"vehicles": entries, "count": len(entries)}
    return vehicle_detections, new_jobs


async def _identify_plateless(db, camera_id, v: dict, vbox: list, ts, frame):
    """Re-identify a plateless vehicle by CLIP appearance. Returns
    (vehicle_id, identity_key, new_description_job_or_None) or (None, None, None)
    when CLIP is unavailable or the crop is unusable."""
    import uuid as _uuid
    from datetime import timedelta

    from services.perception.vlm_gate import get_gate

    crop = _crop(frame, vbox)
    if crop is None or crop.size == 0:
        return None, None, None
    emb = await get_gate().embed_image(crop)
    if emb is None:
        return None, None, None
    vec = emb.tolist()

    cutoff = ts - timedelta(hours=_PLATELESS_RECENCY_HOURS)
    dist = Vehicle.appearance_embedding.cosine_distance(vec)
    row = (await db.execute(
        select(Vehicle, dist.label("d"))
        .where(Vehicle.plateless.is_(True))
        .where(Vehicle.appearance_embedding.is_not(None))
        .where(Vehicle.first_camera_id == camera_id)
        .where(Vehicle.last_seen_at >= cutoff)
        .order_by(dist.asc())
        .limit(1)
    )).first()

    if row is not None and row.d is not None and row.d <= _PLATELESS_MAX_DISTANCE:
        vehicle = row[0]
        vehicle.last_seen_at = ts
        vehicle.sighting_count = (vehicle.sighting_count or 0) + 1
        # EMA the representative embedding so it tracks the vehicle's look.
        old = np.array(vehicle.appearance_embedding, dtype="float32")
        new = 0.8 * old + 0.2 * emb.astype("float32")
        n = np.linalg.norm(new)
        vehicle.appearance_embedding = (new / n).tolist() if n else vec
        job = None
        if vehicle.description_status == "pending" and not vehicle.description:
            job = (vehicle.id, vbox)
        return vehicle.id, vehicle.identity_key, job

    # No match. new provisional plateless identity.
    identity_key = f"plateless:{_uuid.uuid4()}"
    vehicle = Vehicle(
        identity_key=identity_key,
        display_name=f"Unidentified {v.get('label') or 'vehicle'}",
        vehicle_type=v.get("label"),
        plateless=True,
        appearance_embedding=vec,
        first_camera_id=camera_id,
        first_seen_at=ts,
        last_seen_at=ts,
        sighting_count=1,
        is_provisional=True,
        description_status="pending",
    )
    db.add(vehicle)
    await db.flush()
    return vehicle.id, identity_key, (vehicle.id, vbox)


# Cap concurrent vehicle-description VLM calls. a burst of new plates must
# not spawn unbounded calls and starve the live VLM lane. Tasks are also
# tracked so they are not garbage-collected mid-flight.
_DESC_SEMAPHORE = asyncio.Semaphore(2)
_desc_tasks: set = set()


def schedule_descriptions(jobs: list, frame: np.ndarray) -> None:
    """Fire-and-forget VLM descriptions for new vehicles. crops now (the
    frame may be reused), describes in the background so the keyframe path
    is never blocked. Concurrency is bounded by a semaphore."""
    for vehicle_id, bbox in jobs:
        crop = _crop(frame, bbox)
        if crop is None or crop.size == 0:
            continue
        try:
            task = asyncio.create_task(_describe_vehicle_guarded(vehicle_id, crop))
            _desc_tasks.add(task)
            task.add_done_callback(_desc_tasks.discard)
        except RuntimeError:
            pass  # no running loop (sync context). skip description


async def _describe_vehicle_guarded(vehicle_id, crop: np.ndarray) -> None:
    async with _DESC_SEMAPHORE:
        await _describe_vehicle(vehicle_id, crop)


def _crop(frame: np.ndarray, bbox: list) -> np.ndarray | None:
    try:
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2].copy()
    except (ValueError, TypeError, IndexError):
        return None


async def _describe_vehicle(vehicle_id, crop: np.ndarray) -> None:
    """Generate and store a one-line VLM description for a vehicle crop."""
    try:
        from services.perception.vlm import VLMClient, get_active_provider

        provider = await get_active_provider()
        if provider is None:
            return
        client = VLMClient()
        desc = await client.describe(
            crop, [], provider, system_prompt=_VEHICLE_SYSTEM_PROMPT
        )
        desc = (desc or "").strip()
        if not desc:
            raise ValueError("empty description")
        color, make, model = _parse_attributes(desc)
        async with async_session() as db:
            vehicle = await db.get(Vehicle, vehicle_id)
            if vehicle is None:
                return
            vehicle.description = desc[:500]
            vehicle.description_status = "done"
            if color and not vehicle.color:
                vehicle.color = color
            if make and not vehicle.make:
                vehicle.make = make
            if model and not vehicle.model:
                vehicle.model = model
            # Upgrade a placeholder name ("Plate X" / "Unidentified car") to
            # something human once we have color/make.
            placeholder = (vehicle.display_name.startswith("Plate ")
                           or vehicle.display_name.startswith("Unidentified "))
            if placeholder and (color or make):
                label = " ".join(p for p in [color, make, model] if p).strip()
                if label:
                    plate = vehicle.license_plate or ""
                    vehicle.display_name = f"{label} ({plate})" if plate else label
            await db.commit()
    except Exception:
        logger.debug("Vehicle description failed for %s", vehicle_id, exc_info=True)
        try:
            async with async_session() as db:
                vehicle = await db.get(Vehicle, vehicle_id)
                if vehicle is not None:
                    vehicle.description_status = "failed"
                    await db.commit()
        except Exception:
            pass


_KNOWN_MAKES = {
    "toyota", "honda", "nissan", "ford", "chevrolet", "chevy", "bmw", "audi",
    "mercedes", "volkswagen", "vw", "hyundai", "kia", "tesla", "jeep", "mazda",
    "subaru", "volvo", "lexus", "dodge", "ram", "gmc", "porsche", "ferrari",
    "land rover", "range rover", "mitsubishi", "suzuki", "renault", "peugeot",
}
_KNOWN_COLORS = {
    "red", "blue", "green", "black", "white", "silver", "grey", "gray",
    "yellow", "orange", "brown", "beige", "gold", "maroon", "navy", "tan",
}


def _parse_attributes(desc: str) -> tuple[str | None, str | None, str | None]:
    """Best-effort pull of color/make/model from the VLM line."""
    low = desc.lower()
    color = next((c for c in _KNOWN_COLORS if c in low.split()), None)
    make = next((m for m in _KNOWN_MAKES if m in low), None)
    model = None
    if make:
        # Word after the make is often the model.
        toks = low.replace(",", " ").split()
        if make in toks:
            i = toks.index(make)
            if i + 1 < len(toks) and toks[i + 1] not in ("with", "and", "sedan", "suv", "truck", "van"):
                model = toks[i + 1]
    return (
        color.capitalize() if color else None,
        make.capitalize() if make else None,
        model.capitalize() if model else None,
    )
