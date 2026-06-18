"""
Face cluster consolidation.

Live clustering decides one face at a time and can never undo a split: once
two clusters exist for the same person, nothing in the hot path merges them.
Pose, lighting and the occasional bad crop guarantee some splits, so a
periodic offline pass is what keeps the People page from showing one person as
several "Unknown" entries.

Two jobs, run together every `face_cluster_merge_interval_seconds`:

1. Merge pending<->pending. Pending clusters whose nearest real samples sit
   within a conservative distance are the same person; fold them into one
   (the absorbed clusters are marked status='merged' and their samples are
   reassigned to the survivor). Merging is destructive, so the bar is tighter
   than the live clustering threshold.

2. Attach pending->named. A pending cluster that matches an already-enrolled
   Person is that person seen again; link it and copy its samples into the
   Person's embedding gallery (continuous enrollment). This directly heals the
   case where someone was named from one cluster while another cluster of the
   same person lingered as "Unknown".

Both are cheap for a household-sized cluster set and run alongside the body
re-id sweeper.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from sqlalchemy import select, update

from services.perception.faces import MAX_CLUSTER_SAMPLES, _renorm
from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import FaceCluster, FaceClusterSample, FaceEmbedding, Person

logger = logging.getLogger("nurby.perception.face_merger")

# Conservative defaults (L2 on unit ArcFace embeddings). Overridable via
# app_settings. Merging is destructive so the bar is tighter than the live
# CLUSTER_THRESHOLD (1.0); attaching to a named person sits just under
# MATCH_THRESHOLD (1.1) for the same reason.
DEFAULT_MERGE_THRESHOLD = 0.85
DEFAULT_ATTACH_THRESHOLD = 1.0
# A coarse representative-distance filter trims the O(n^2) pair scan before the
# exact nearest-sample refinement. Padded well above the merge band.
COARSE_PAD = 0.5
# Safety cap. Past this many pending clusters we skip the quadratic merge pass
# and log, rather than stall the loop.
MAX_PENDING_FOR_MERGE = 600


class _UnionFind:
    def __init__(self, ids):
        self._parent = {i: i for i in ids}

    def find(self, x):
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self):
        out: dict = {}
        for i in self._parent:
            out.setdefault(self.find(i), []).append(i)
        return [g for g in out.values() if len(g) > 1]


class FaceClusterMerger:
    """Periodic merge of duplicate face clusters + attach to named persons."""

    def __init__(self) -> None:
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("face cluster merger started")
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except Exception:
                    logger.exception("face cluster merger tick failed")
                interval = int(await get_setting(
                    "face_cluster_merge_interval_seconds", 600,
                ))
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=max(60, interval),
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("face cluster merger stopped")

    async def _tick(self) -> None:
        merge_thr = float(await get_setting(
            "face_cluster_merge_threshold", DEFAULT_MERGE_THRESHOLD,
        ))
        attach_thr = float(await get_setting(
            "face_cluster_attach_threshold", DEFAULT_ATTACH_THRESHOLD,
        ))
        async with async_session() as db:
            merged = await self._merge_pending(db, merge_thr)
            attached = await self._attach_to_named(db, attach_thr)
            await db.commit()
        if merged or attached:
            logger.info(
                "face cluster merge pass. merged=%d attached=%d", merged, attached,
            )

    # ------------------------------------------------------------------

    async def _cluster_embeddings(self, db, cluster_ids) -> dict:
        """{cluster_id: [representative, *recent_samples]} as np arrays."""
        out: dict = {}
        reps = (await db.execute(
            select(FaceCluster.id, FaceCluster.representative_embedding)
            .where(FaceCluster.id.in_(cluster_ids))
        )).all()
        for cid, rep in reps:
            out[cid] = [np.array(rep)]
        samples = (await db.execute(
            select(FaceClusterSample.cluster_id, FaceClusterSample.embedding)
            .where(FaceClusterSample.cluster_id.in_(cluster_ids))
            .order_by(FaceClusterSample.captured_at.desc())
        )).all()
        counts: dict = {}
        for cid, emb in samples:
            if counts.get(cid, 0) >= MAX_CLUSTER_SAMPLES:
                continue
            out.setdefault(cid, []).append(np.array(emb))
            counts[cid] = counts.get(cid, 0) + 1
        return out

    @staticmethod
    def _nearest(embs_a, embs_b) -> float:
        return min(
            float(np.linalg.norm(a - b)) for a in embs_a for b in embs_b
        )

    async def _merge_pending(self, db, merge_thr: float) -> int:
        rows = (await db.execute(
            select(
                FaceCluster.id,
                FaceCluster.representative_embedding,
                FaceCluster.sighting_count,
                FaceCluster.first_seen_at,
            ).where(FaceCluster.status == "pending")
        )).all()
        if len(rows) < 2:
            return 0
        if len(rows) > MAX_PENDING_FOR_MERGE:
            logger.warning(
                "skipping face merge pass. %d pending clusters exceeds cap %d",
                len(rows), MAX_PENDING_FOR_MERGE,
            )
            return 0

        ids = [r[0] for r in rows]
        reps = {r[0]: np.array(r[1]) for r in rows}
        embs = await self._cluster_embeddings(db, ids)

        # Coarse representative filter, then exact nearest-sample refinement.
        uf = _UnionFind(ids)
        coarse = merge_thr + COARSE_PAD
        n = len(ids)
        for i in range(n):
            ai = ids[i]
            for j in range(i + 1, n):
                bj = ids[j]
                if float(np.linalg.norm(reps[ai] - reps[bj])) > coarse:
                    continue
                if self._nearest(embs[ai], embs[bj]) < merge_thr:
                    uf.union(ai, bj)

        merged = 0
        for group in uf.groups():
            survivor_id = await self._merge_group(db, group)
            if survivor_id is not None:
                merged += len(group) - 1
        return merged

    async def _merge_group(self, db, group) -> object | None:
        clusters = {}
        for cid in group:
            c = await db.get(FaceCluster, cid)
            if c is not None and c.status == "pending":
                clusters[cid] = c
        if len(clusters) < 2:
            return None

        # Survivor: most-seen, tie broken by earliest first_seen_at.
        survivor = max(
            clusters.values(),
            key=lambda c: (c.sighting_count or 0, -(c.first_seen_at.timestamp() if c.first_seen_at else 0)),
        )
        absorbed = [c for c in clusters.values() if c.id != survivor.id]
        absorbed_ids = [c.id for c in absorbed]

        # Move every absorbed sample onto the survivor.
        await db.execute(
            update(FaceClusterSample)
            .where(FaceClusterSample.cluster_id.in_(absorbed_ids))
            .values(cluster_id=survivor.id)
        )
        await db.flush()

        # Recompute the survivor representative from its full (post-merge)
        # sample set, renormalized back onto the unit sphere.
        sample_embs = (await db.execute(
            select(FaceClusterSample.embedding)
            .where(FaceClusterSample.cluster_id == survivor.id)
        )).scalars().all()
        if sample_embs:
            mean = np.mean([np.array(e) for e in sample_embs], axis=0)
            survivor.representative_embedding = _renorm(mean).tolist()

        survivor.sighting_count = (survivor.sighting_count or 0) + sum(
            c.sighting_count or 0 for c in absorbed
        )
        for c in absorbed:
            if c.first_seen_at and (not survivor.first_seen_at or c.first_seen_at < survivor.first_seen_at):
                survivor.first_seen_at = c.first_seen_at
            if c.last_seen_at and (not survivor.last_seen_at or c.last_seen_at > survivor.last_seen_at):
                survivor.last_seen_at = c.last_seen_at
            if not survivor.sample_thumbnail_path and c.sample_thumbnail_path:
                survivor.sample_thumbnail_path = c.sample_thumbnail_path
            # Keep the row (observations reference cluster_id) but drop it out
            # of clustering and the suggestion list.
            c.status = "merged"
            c.sighting_count = 0
        logger.info(
            "merged %d face cluster(s) into %s", len(absorbed), survivor.id,
        )
        return survivor.id

    # ------------------------------------------------------------------

    async def _attach_to_named(self, db, attach_thr: float) -> int:
        known = (await db.execute(
            select(FaceEmbedding.person_id, FaceEmbedding.embedding)
            .join(Person, FaceEmbedding.person_id == Person.id)
            .where(Person.consent_given.is_(True))
        )).all()
        if not known:
            return 0
        known_by_person: dict = {}
        for pid, emb in known:
            known_by_person.setdefault(pid, []).append(np.array(emb))

        pending = (await db.execute(
            select(FaceCluster.id).where(FaceCluster.status == "pending")
        )).scalars().all()
        if not pending:
            return 0
        embs = await self._cluster_embeddings(db, pending)

        attached = 0
        for cid in pending:
            cluster_embs = embs.get(cid)
            if not cluster_embs:
                continue
            best_person = None
            best_dist = float("inf")
            for pid, person_embs in known_by_person.items():
                d = min(
                    float(np.linalg.norm(ce - pe))
                    for ce in cluster_embs for pe in person_embs
                )
                if d < best_dist:
                    best_dist = d
                    best_person = pid
            if best_person is None or best_dist >= attach_thr:
                continue
            await self._attach_cluster(db, cid, best_person)
            attached += 1
        return attached

    async def _attach_cluster(self, db, cluster_id, person_id) -> None:
        cluster = await db.get(FaceCluster, cluster_id)
        if cluster is None or cluster.status != "pending":
            return
        cluster.person_id = person_id
        cluster.status = "named"
        # Continuous enrollment: fold this cluster's samples into the person's
        # gallery so future detections at these angles match directly.
        sample_embs = (await db.execute(
            select(FaceClusterSample.embedding)
            .where(FaceClusterSample.cluster_id == cluster_id)
            .order_by(FaceClusterSample.captured_at.desc())
            .limit(MAX_CLUSTER_SAMPLES)
        )).scalars().all()
        for emb in sample_embs:
            db.add(FaceEmbedding(
                person_id=person_id,
                embedding=emb,
                source="detection",
            ))
        logger.info(
            "attached pending cluster %s to person %s (+%d embeddings)",
            cluster_id, person_id, len(sample_embs),
        )
