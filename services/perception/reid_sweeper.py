"""
Body re-identification housekeeping.

Two scheduled jobs.

1. Tentative decay. Body clusters with no face co-verification and no
   activity for N days get marked status='ignored' so they drop out of
   the suggestion list and the cluster search. This is the durable
   answer to "we never confirmed who that was; stop tracking them."

2. Body+face overlap fusion. When a body cluster and a face cluster
   appear together on the same observation window and share a Journey
   slot, the body cluster inherits the face cluster's Person link. This
   closes the loop on "saw their face for the first time today, all
   the body-only sightings from the past hour should retroactively
   collapse to that Person."

Both jobs are cheap enough to run alongside the daily digest scheduler.
Tick every `body_reid_fusion_interval_seconds` (default 5 min).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.recurrence_notifications import reconcile_recurrence_notifications
from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import (
    BodyCluster,
    BodyClusterSample,
    FaceCluster,
    Notification,
    Observation,
)

logger = logging.getLogger("nurby.perception.reid_sweeper")


class BodyReIDSweeper:
    """Periodic decay + face-overlap fusion for body clusters."""

    def __init__(self) -> None:
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("body re-id sweeper started")
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except Exception:
                    logger.exception("body re-id sweeper tick failed")
                interval = int(await get_setting(
                    "body_reid_fusion_interval_seconds", 300,
                ))
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=max(60, interval),
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("body re-id sweeper stopped")

    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        async with async_session() as db:
            await self._decay_tentative(db)
            await self._fuse_face_overlaps(db)
            await self._merge_tentative(db)
            await db.commit()
        # Phase 4. Prompt the household to name new clusters that
        # crossed the sightings threshold. Wrapped in a try so a
        # Telegram outage never breaks the perception sweep.
        try:
            await self._prompt_cluster_naming()
        except Exception:
            logger.exception("cluster naming prompts failed")

    async def _prompt_cluster_naming(self) -> None:
        """Send a Telegram naming prompt for any face or body cluster
        that just crossed the configured sighting threshold.

        Idempotent. ``naming_prompted_at`` is stamped on first send so
        we never re-prompt the same cluster. Requires at least one
        ``shared_with_household=true`` or paired channel; the
        initiator module no-ops otherwise so a deployment without
        Telegram doesn't trip on this code path.
        """
        from services.notify.cluster_naming_telegram import (
            request_body_cluster_naming,
            request_face_cluster_naming,
        )

        # Threshold knobs share the existing app_settings table so an
        # ops user can flip them without a redeploy.
        min_sightings = int(await get_setting("cluster_naming_min_sightings", 3))
        if min_sightings <= 0:
            return

        async with async_session() as db:
            face_rows = (
                await db.execute(
                    select(FaceCluster.id)
                    .where(FaceCluster.status == "pending")
                    .where(FaceCluster.sighting_count >= min_sightings)
                    .where(FaceCluster.naming_prompted_at.is_(None))
                    .limit(5)
                )
            ).all()
            body_rows = (
                await db.execute(
                    select(BodyCluster.id)
                    .where(BodyCluster.status == "pending")
                    .where(BodyCluster.person_id.is_(None))
                    .where(BodyCluster.sighting_count >= min_sightings)
                    .where(BodyCluster.naming_prompted_at.is_(None))
                    .limit(5)
                )
            ).all()

        for (fc_id,) in face_rows:
            try:
                await request_face_cluster_naming(fc_id)
            except Exception:
                logger.exception(
                    "request_face_cluster_naming failed cluster=%s", fc_id,
                )
        for (bc_id,) in body_rows:
            try:
                await request_body_cluster_naming(bc_id)
            except Exception:
                logger.exception(
                    "request_body_cluster_naming failed cluster=%s", bc_id,
                )

    async def _decay_tentative(self, db: AsyncSession) -> None:
        """Mark long-stale tentative clusters as ignored."""
        days = int(await get_setting("body_reid_tentative_decay_days", 14))
        if days <= 0:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(
            update(BodyCluster)
            .where(BodyCluster.status == "pending")
            .where(BodyCluster.confidence == "tentative")
            .where(BodyCluster.person_id.is_(None))
            .where(BodyCluster.last_seen_at < cutoff)
            .values(status="ignored")
            .returning(BodyCluster.id)
        )
        ids = list(result.scalars().all())
        if ids:
            logger.info(
                "body re-id decay. ignored %d tentative cluster(s) idle > %dd",
                len(ids), days,
            )

    async def _fuse_face_overlaps(self, db: AsyncSession) -> None:
        """Promote tentative body clusters when they co-occur with a
        named face cluster on the same observation.

        Walks recent observations carrying both `faces` and `bodies`
        in `person_detections`. For each such observation, if any face
        in the payload maps to a Person and any body cluster is still
        tentative, link the body cluster to that Person and flip its
        confidence to confirmed.
        """
        # Look back over the last hour. Cheaper than scanning forever.
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        rows = (
            await db.execute(
                select(Observation.id, Observation.person_detections)
                .where(Observation.started_at >= since)
                .where(Observation.person_detections.is_not(None))
            )
        ).all()

        promoted = 0
        for obs_id, pd in rows:
            if not isinstance(pd, dict):
                continue
            faces = pd.get("faces") or []
            bodies = pd.get("bodies") or []
            if not faces or not bodies:
                continue

            # Pull face cluster IDs whose face cluster is linked to a Person.
            face_cluster_ids = []
            for f in faces:
                cid = f.get("cluster_id")
                if cid:
                    try:
                        face_cluster_ids.append(uuid_from(cid))
                    except Exception:
                        pass
            if not face_cluster_ids:
                continue
            fc_rows = (
                await db.execute(
                    select(FaceCluster.id, FaceCluster.person_id)
                    .where(FaceCluster.id.in_(face_cluster_ids))
                    .where(FaceCluster.person_id.is_not(None))
                )
            ).all()
            if not fc_rows:
                continue
            # Pick the first named face cluster. Multi-person frames
            # produce ambiguous links; we conservatively skip body
            # promotion when more than one named face is present.
            if len({r.person_id for r in fc_rows}) > 1:
                continue
            person_id = fc_rows[0].person_id
            face_cluster_id = fc_rows[0].id

            for b in bodies:
                bc_id = b.get("body_cluster_id")
                if not bc_id:
                    continue
                try:
                    bc_uuid = uuid_from(bc_id)
                except Exception:
                    continue
                cluster = await db.get(BodyCluster, bc_uuid)
                if cluster is None:
                    continue
                if cluster.person_id is not None and cluster.person_id == person_id:
                    continue
                if cluster.confidence == "confirmed" and cluster.person_id is not None:
                    continue
                cluster.person_id = person_id
                cluster.linked_face_cluster_id = face_cluster_id
                cluster.confidence = "confirmed"
                promoted += 1
        if promoted:
            logger.info(
                "body re-id fusion. promoted %d body cluster(s) via face overlap",
                promoted,
            )

    async def _merge_tentative(self, db: AsyncSession) -> int:
        """Merge conservatively duplicate anonymous body clusters.

        Body re-identification is intentionally approximate, so this only
        considers pending/tentative clusters and requires both representative
        and nearest-sample distances to clear a tight threshold.  Confirmed or
        person-linked clusters are never merged by this housekeeping pass.
        """
        threshold = float(await get_setting("body_reid_merge_threshold", 0.85))
        rows = (await db.execute(
            select(
                BodyCluster.id,
                BodyCluster.representative_embedding,
            )
            .where(BodyCluster.status == "pending")
            .where(BodyCluster.confidence == "tentative")
            .where(BodyCluster.person_id.is_(None))
        )).all()
        if len(rows) < 2 or len(rows) > 600:
            return 0

        ids = [row[0] for row in rows]
        reps = {row[0]: np.array(row[1]) for row in rows}
        samples = (await db.execute(
            select(BodyClusterSample.cluster_id, BodyClusterSample.embedding)
            .where(BodyClusterSample.cluster_id.in_(ids))
            .order_by(BodyClusterSample.captured_at.desc())
        )).all()
        embeddings: dict = {cluster_id: [reps[cluster_id]] for cluster_id in ids}
        counts: dict = {}
        for cluster_id, embedding in samples:
            if counts.get(cluster_id, 0) >= 24:
                continue
            embeddings.setdefault(cluster_id, []).append(np.array(embedding))
            counts[cluster_id] = counts.get(cluster_id, 0) + 1

        groups = []
        for index, left_id in enumerate(ids):
            for right_id in ids[index + 1:]:
                if float(np.linalg.norm(reps[left_id] - reps[right_id])) > threshold + 0.5:
                    continue
                nearest = min(
                    float(np.linalg.norm(left - right))
                    for left in embeddings[left_id]
                    for right in embeddings[right_id]
                )
                if nearest < threshold:
                    groups.append((left_id, right_id))

        merged = 0
        for left_id, right_id in groups:
            left = await db.get(BodyCluster, left_id)
            right = await db.get(BodyCluster, right_id)
            if not left or not right:
                continue
            if not all((cluster.status == "pending", cluster.confidence == "tentative", cluster.person_id is None)
                       for cluster in (left, right)):
                continue
            survivor, absorbed = (
                (left, right)
                if (left.sighting_count or 0, -(left.first_seen_at.timestamp() if left.first_seen_at else 0))
                >= (right.sighting_count or 0, -(right.first_seen_at.timestamp() if right.first_seen_at else 0))
                else (right, left)
            )
            absorbed_marker = f"recurring_unknown:body:{absorbed.id}"
            survivor_marker = f"recurring_unknown:body:{survivor.id}"
            notifications = (await db.execute(
                select(Notification).where(Notification.dedupe_key == absorbed_marker)
            )).scalars().all()
            reconcile_recurrence_notifications(notifications, survivor_marker)
            await db.execute(
                update(BodyClusterSample)
                .where(BodyClusterSample.cluster_id == absorbed.id)
                .values(cluster_id=survivor.id)
            )
            await db.flush()
            moved_embeddings = (await db.execute(
                select(BodyClusterSample.embedding)
                .where(BodyClusterSample.cluster_id == survivor.id)
            )).scalars().all()
            if moved_embeddings:
                representative = np.mean(
                    [np.array(embedding) for embedding in moved_embeddings], axis=0
                )
                norm = np.linalg.norm(representative)
                if norm:
                    representative = representative / norm
                survivor.representative_embedding = representative.tolist()
            survivor.sighting_count = (survivor.sighting_count or 0) + (absorbed.sighting_count or 0)
            if absorbed.first_seen_at and (
                not survivor.first_seen_at
                or absorbed.first_seen_at < survivor.first_seen_at
            ):
                survivor.first_seen_at = absorbed.first_seen_at
            if absorbed.last_seen_at and (
                not survivor.last_seen_at
                or absorbed.last_seen_at > survivor.last_seen_at
            ):
                survivor.last_seen_at = absorbed.last_seen_at
            if not survivor.sample_thumbnail_path and absorbed.sample_thumbnail_path:
                survivor.sample_thumbnail_path = absorbed.sample_thumbnail_path
            absorbed.status = "merged"
            absorbed.sighting_count = 0
            merged += 1
        if merged:
            logger.info("body re-id merge. merged %d tentative cluster(s)", merged)
        return merged


def uuid_from(value):
    import uuid as _uuid
    if isinstance(value, _uuid.UUID):
        return value
    return _uuid.UUID(str(value))
