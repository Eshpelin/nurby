"""The demo footage only yields a few distinct faces, so seeding more
people than that makes two cards show the same person. Keep one person
per distinct face cluster, repoint the duplicates' sightings onto the
kept person, and delete the rest. Run in the api container."""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from shared.database import async_session
from shared.models import Observation, Person


def cluster_of(p: Person) -> str | None:
    if not p.photo_path:
        return None
    return os.path.basename(p.photo_path).split("_")[0]


async def main():
    async with async_session() as db:
        people = list((await db.execute(select(Person).order_by(Person.created_at))).scalars())
        keep: dict[str, Person] = {}
        drop: list[Person] = []
        for p in people:
            c = cluster_of(p)
            if c and c not in keep:
                keep[c] = p
            else:
                drop.append(p)

        # Repoint observations of dropped people onto the kept person that
        # shares their face cluster, so sightings/last-seen stay intact.
        obs = list((await db.execute(
            select(Observation).where(Observation.person_detections.is_not(None))
        )).scalars())
        drop_ids = {str(p.id): keep.get(cluster_of(p)) for p in drop}
        repointed = 0
        for o in obs:
            pd = o.person_detections or {}
            changed = False
            for face in pd.get("faces", []):
                pid = str(face.get("person_id")) if face.get("person_id") else None
                if pid in drop_ids and drop_ids[pid] is not None:
                    face["person_id"] = str(drop_ids[pid].id)
                    pd["person_name"] = drop_ids[pid].display_name
                    changed = True
            if changed:
                o.person_detections = dict(pd)
                repointed += 1

        for p in drop:
            await db.delete(p)
        await db.commit()

        # Tidy the kept names so there is no "Unknown person 2" left over.
        kept = list((await db.execute(select(Person).order_by(Person.created_at))).scalars())
        n = 0
        for p in kept:
            if p.display_name.lower().startswith("unknown person"):
                p.display_name = "Unknown person"
                p.nickname = None
                n += 1
        await db.commit()
        print(f"kept {len(kept)} distinct people, dropped {len(drop)}, "
              f"repointed {repointed} observations")
        for p in kept:
            print("  -", p.display_name, "::", cluster_of(p))


if __name__ == "__main__":
    asyncio.run(main())
