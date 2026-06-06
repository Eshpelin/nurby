"""Swap the seeded placeholder imagery for REAL crops the pipeline cut
from the demo video. People get distinct real face crops, vehicles get
real frames that actually contain a vehicle. Run in the api container."""

from __future__ import annotations

import asyncio
import glob
import os
import random

from sqlalchemy import select

from shared.config import settings
from shared.database import async_session
from shared.models import Observation, Person, Vehicle

random.seed(11)
THUMBS = settings.thumbnails_path


async def main():
    faces = sorted(glob.glob(os.path.join(THUMBS, "faces", "*.jpg")))
    # one crop per distinct face cluster (prefix before first underscore)
    by_cluster: dict[str, str] = {}
    for f in faces:
        key = os.path.basename(f).split("_")[0]
        by_cluster.setdefault(key, f)
    crops = list(by_cluster.values())
    # If there are not enough distinct clusters, fill from other crop files
    # (different timestamps) so every seeded person still gets a real face.
    if len(crops) < 5:
        extra = [f for f in faces if f not in crops]
        # spread picks across the set so they are not near-duplicate frames
        step = max(1, len(extra) // 6)
        crops += extra[::step]
    # de-dup preserve order
    seen_c, uniq = set(), []
    for c in crops:
        if c not in seen_c:
            seen_c.add(c)
            uniq.append(c)
    crops = uniq
    random.shuffle(crops)

    async with async_session() as db:
        people = list((await db.execute(select(Person).order_by(Person.created_at))).scalars())
        for i, p in enumerate(people):
            if i < len(crops):
                p.photo_path = crops[i]
        # real frames that contain a vehicle. pipeline observations only
        # (vlm_provider is null = not our seeded rows), label car/truck/van/bus.
        obs = list((await db.execute(
            select(Observation)
            .where(Observation.vlm_provider.is_(None))
            .where(Observation.thumbnail_path.is_not(None))
            .order_by(Observation.started_at.desc())
            .limit(800)
        )).scalars())
        veh_frames = []
        for o in obs:
            od = o.object_detections or {}
            labels = {x.get("label") for x in od.get("objects", [])}
            if labels & {"car", "truck", "van", "bus", "motorcycle"}:
                if os.path.exists(o.thumbnail_path):
                    veh_frames.append(o.thumbnail_path)
        # de-dup, keep distinct frames
        seen, picks = set(), []
        for f in veh_frames:
            if f not in seen:
                seen.add(f)
                picks.append(f)
        random.shuffle(picks)

        vehicles = list((await db.execute(select(Vehicle).order_by(Vehicle.created_at))).scalars())
        for i, v in enumerate(vehicles):
            if i < len(picks):
                v.photo_path = picks[i]

        await db.commit()
        print(f"people with real faces: {min(len(people), len(crops))} "
              f"(of {len(crops)} distinct crops)")
        print(f"vehicles with real frames: {min(len(vehicles), len(picks))} "
              f"(of {len(picks)} car frames found)")


if __name__ == "__main__":
    asyncio.run(main())
