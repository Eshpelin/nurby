"""Digest scheduler. Periodically generates observation summaries for cameras with digests enabled."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import async_session
from shared.models import Camera, DigestEntry, Observation, Person

logger = logging.getLogger(__name__)

PERIOD_HOURS = {
    "1h": 1,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "48h": 48,
    "7d": 168,
}

CHECK_INTERVAL = 60  # seconds between checks


async def _last_digest_time(db: AsyncSession, camera_id) -> datetime | None:
    result = await db.execute(
        select(DigestEntry.generated_at)
        .where(DigestEntry.camera_id == camera_id)
        .order_by(DigestEntry.generated_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


async def _generate_camera_digest(db: AsyncSession, camera: Camera, since: datetime) -> None:

    # Count observations in the period
    obs_count_result = await db.execute(
        select(func.count())
        .select_from(Observation)
        .where(Observation.camera_id == camera.id, Observation.started_at >= since)
    )
    total_obs = obs_count_result.scalar() or 0

    if total_obs == 0:
        return  # Nothing to digest

    # Get unique persons detected
    obs_rows = await db.execute(
        select(Observation.person_detections)
        .where(
            Observation.camera_id == camera.id,
            Observation.started_at >= since,
            Observation.person_detections.isnot(None),
        )
    )

    person_ids = set()
    for (person_det,) in obs_rows:
        if isinstance(person_det, dict) and "persons" in person_det:
            for p in person_det["persons"]:
                pid = p.get("person_id")
                if pid:
                    person_ids.add(pid)

    # Get object detection counts
    obj_rows = await db.execute(
        select(Observation.object_detections)
        .where(
            Observation.camera_id == camera.id,
            Observation.started_at >= since,
            Observation.object_detections.isnot(None),
        )
    )

    object_counts: dict[str, int] = {}
    for (obj_det,) in obj_rows:
        if isinstance(obj_det, dict) and "detections" in obj_det:
            for det in obj_det["detections"]:
                label = det.get("label", "unknown")
                object_counts[label] = object_counts.get(label, 0) + 1

    # Get person names
    person_names = []
    if person_ids:
        persons_result = await db.execute(
            select(Person.display_name, Person.nickname).where(
                Person.id.in_(list(person_ids))
            )
        )
        person_names = [
            (nk.strip() if isinstance(nk, str) and nk.strip() else dn)
            for (dn, nk) in persons_result
        ]

    # Build summary text
    period_label = camera.digest_period
    parts = [f"{total_obs} observations in the last {period_label}"]

    if person_names:
        parts.append(f"Persons seen. {', '.join(person_names)}")
    unknown_count = len(person_ids) - len(person_names)
    if unknown_count > 0:
        parts.append(f"{unknown_count} unknown face(s)")

    if object_counts:
        top_objects = sorted(object_counts.items(), key=lambda x: -x[1])[:5]
        obj_parts = [f"{label} ({count})" for label, count in top_objects]
        parts.append(f"Top detections. {', '.join(obj_parts)}")

    summary = ". ".join(parts)

    # Build highlights
    highlights = []
    if person_names:
        highlights.append(f"Recognized {len(person_names)} known person(s)")
    if "car" in object_counts or "truck" in object_counts:
        vehicle_count = object_counts.get("car", 0) + object_counts.get("truck", 0)
        highlights.append(f"{vehicle_count} vehicle detection(s)")

    stats = {
        "total_observations": total_obs,
        "unique_persons": len(person_ids),
        "object_counts": object_counts,
    }

    digest = DigestEntry(
        camera_id=camera.id,
        period=period_label,
        summary=summary,
        highlights=highlights if highlights else None,
        stats=stats,
        total_observations=total_obs,
    )
    db.add(digest)
    await db.commit()
    logger.info("Generated digest for camera %s. %d observations", camera.name, total_obs)


async def run_digest_loop() -> None:
    logger.info("Digest scheduler started")
    while True:
        try:
            async with async_session() as db:
                # Get all cameras with digests enabled
                result = await db.execute(
                    select(Camera).where(Camera.digest_enabled.is_(True))
                )
                cameras = result.scalars().all()

                now = datetime.now(timezone.utc)

                for camera in cameras:
                    try:
                        interval_hours = PERIOD_HOURS.get(camera.digest_period, 24)
                        last_digest = await _last_digest_time(db, camera.id)

                        if last_digest is not None:
                            next_due = last_digest + timedelta(hours=interval_hours)
                            if now < next_due:
                                continue
                            since = last_digest
                        else:
                            since = now - timedelta(hours=interval_hours)

                        await _generate_camera_digest(db, camera, since)
                    except Exception:
                        logger.exception("Failed to generate digest for camera %s", camera.name)

        except Exception:
            logger.exception("Digest scheduler loop error")

        await asyncio.sleep(CHECK_INTERVAL)
