"""
Async VLM queue with backpressure handling.

Decouples VLM calls from the main perception pipeline so detection,
face matching, and observation storage are never blocked by slow VLM
responses. Tracks latency per camera and broadcasts status via WebSocket.

Key design decisions.
- Bounded queue per camera (max 2 pending). Newer frames replace older ones.
- Single VLM worker per camera. No concurrent calls to same model for same feed.
- Latency stats tracked with exponential moving average.
- Observations stored immediately without VLM. Description patched in async.
- WebSocket broadcasts VLM status changes so frontend can show indicators.
"""

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import cv2
import numpy as np

from shared.config import settings
from shared.database import async_session
from shared.models import Observation, Provider
from services.perception.vlm import VLMClient
from services.search.embeddings import generate_embedding, get_embedding_provider

THUMBNAIL_DIR = os.path.join(settings.thumbnails_path, "observations")


def _write_vlm_thumbnail(
    camera_id: str,
    observation_id: uuid.UUID,
    frame: np.ndarray,
    detections: list[dict],
) -> str | None:
    """Save the exact frame the VLM analyzed as a thumbnail.

    Drawn with detection boxes so the image matches what the caption
    describes. Overwrites any earlier thumbnail for this observation
    so the UI always shows the frame that produced the caption.
    """
    try:
        annotated = frame.copy()
        for det in detections:
            try:
                x1, y1, x2, y2 = det["bbox"]
            except (KeyError, ValueError):
                continue
            is_plate = det.get("label") == "license_plate"
            color = (0, 200, 255) if is_plate else (0, 255, 0)
            label = (
                f"PLATE {det.get('plate_text', '?')}"
                if is_plate and det.get("plate_text")
                else f"{det.get('label', '?')} {det.get('confidence', 0):.0%}"
            )
            cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
            cv2.putText(
                annotated, label, (int(x1), int(y1) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )
        os.makedirs(THUMBNAIL_DIR, exist_ok=True)
        filename = f"{camera_id}_obs_{observation_id}_vlm.jpg"
        path = os.path.join(THUMBNAIL_DIR, filename)
        cv2.imwrite(path, annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return path
    except Exception:
        logger.exception("Failed to save VLM thumbnail for observation %s", observation_id)
        return None

logger = logging.getLogger("nurby.perception.vlm_queue")

# Module-level stats registry so API can read without direct pipeline reference
_global_stats: dict[str, "CameraVLMStats"] = {}


def get_vlm_stats() -> dict[str, dict]:
    """Get VLM stats for all cameras. Safe to call from any context."""
    return {cid: s.to_dict() for cid, s in _global_stats.items()}


@dataclass
class VLMJob:
    """A pending VLM call."""
    camera_id: str
    observation_id: uuid.UUID
    frame: np.ndarray
    detections: list[dict]
    provider: Provider
    system_prompt: str | None
    max_tokens: int | None
    timestamp: datetime
    max_input_tokens: int | None = None
    heard_text: str | None = None
    extra_context: str | None = None
    # Cascade refiner config. When refiner_provider is set, the worker
    # evaluates the trigger lists against the primary's output after
    # the first call returns and, on a hit, fires a second call to the
    # refiner provider with the primary's text spliced into
    # extra_context. The refined text replaces the observation's
    # vlm_description; the primary text is preserved on the row for
    # the UI's before/after popover.
    refiner_provider: Provider | None = None
    refiner_trigger_objects: list[str] | None = None
    refiner_keywords: list[str] | None = None
    refiner_max_tokens: int | None = None
    refiner_max_input_tokens: int | None = None
    enqueued_at: float = field(default_factory=time.monotonic)


@dataclass
class CameraVLMStats:
    """Per-camera VLM performance stats."""
    avg_latency: float = 0.0       # exponential moving average in seconds
    last_latency: float = 0.0      # most recent call duration
    total_calls: int = 0
    total_errors: int = 0
    total_dropped: int = 0         # frames dropped due to backpressure
    last_call_at: float = 0.0      # monotonic timestamp
    last_result_at: float = 0.0    # monotonic timestamp
    status: str = "idle"           # idle, processing, slow, stalled

    def record_latency(self, duration: float):
        self.last_latency = duration
        self.total_calls += 1
        self.last_result_at = time.monotonic()
        # Exponential moving average (alpha=0.3 for responsiveness)
        if self.avg_latency == 0:
            self.avg_latency = duration
        else:
            self.avg_latency = 0.3 * duration + 0.7 * self.avg_latency

    def record_error(self):
        self.total_errors += 1
        self.last_result_at = time.monotonic()

    def record_drop(self):
        self.total_dropped += 1

    def update_status(self):
        now = time.monotonic()
        if self.status == "idle":
            return
        # Stalled if no result in 5 minutes while processing
        if self.last_call_at > 0 and (now - self.last_call_at) > 300:
            self.status = "stalled"
        elif self.avg_latency > 10:
            self.status = "slow"

    def to_dict(self) -> dict:
        self.update_status()
        return {
            "avg_latency": round(self.avg_latency, 2),
            "last_latency": round(self.last_latency, 2),
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "total_dropped": self.total_dropped,
            "status": self.status,
        }


class VLMQueue:
    """Bounded async queue for VLM calls with per-camera workers."""

    MAX_PENDING_PER_CAMERA = 2  # keep latest N frames, drop older

    def __init__(self, vlm_client: VLMClient | None = None):
        self._vlm = vlm_client or VLMClient()
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._stats: dict[str, CameraVLMStats] = {}
        self._broadcast_fn = None  # set via set_broadcast()
        self._running = False

    def set_broadcast(self, fn):
        """Set the WebSocket broadcast function (from services.api.ws)."""
        self._broadcast_fn = fn

    def get_stats(self, camera_id: str) -> CameraVLMStats:
        if camera_id not in self._stats:
            self._stats[camera_id] = CameraVLMStats()
        return self._stats[camera_id]

    def get_all_stats(self) -> dict[str, dict]:
        return {cid: s.to_dict() for cid, s in self._stats.items()}

    async def enqueue(self, job: VLMJob):
        """Submit a VLM job. Drops oldest if queue full."""
        camera_id = job.camera_id

        if camera_id not in self._queues:
            self._queues[camera_id] = asyncio.Queue(maxsize=self.MAX_PENDING_PER_CAMERA)
            stats = CameraVLMStats()
            self._stats[camera_id] = stats
            _global_stats[camera_id] = stats  # expose to API via get_vlm_stats()

        q = self._queues[camera_id]

        # If queue full, drop oldest (backpressure)
        while q.full():
            try:
                dropped = q.get_nowait()
                self._stats[camera_id].record_drop()
                logger.info(
                    "VLM backpressure for camera %s. Dropped frame from %s (queue full)",
                    camera_id, dropped.timestamp.isoformat(),
                )
            except asyncio.QueueEmpty:
                break

        await q.put(job)

        # Surface a "queued" state immediately so the tile shows a
        # signal during the (usually short) gap between enqueue and
        # the worker picking the job up. The worker will overwrite
        # this with "processing" on its next iteration.
        stats = self._stats[camera_id]
        if stats.status == "idle":
            stats.status = "queued"
            await self._broadcast_status(camera_id)

        # Start worker if not running
        if camera_id not in self._workers or self._workers[camera_id].done():
            self._workers[camera_id] = asyncio.create_task(
                self._worker(camera_id),
                name=f"vlm-worker-{camera_id[:8]}",
            )

    async def _worker(self, camera_id: str):
        """Process VLM jobs for a single camera sequentially."""
        q = self._queues[camera_id]
        stats = self._stats[camera_id]

        while True:
            try:
                job = await asyncio.wait_for(q.get(), timeout=60)
            except asyncio.TimeoutError:
                # No work for 60s, shut down worker
                stats.status = "idle"
                await self._broadcast_status(camera_id)
                logger.debug("VLM worker for camera %s idle, shutting down", camera_id)
                return

            stats.status = "processing"
            stats.last_call_at = time.monotonic()
            await self._broadcast_status(camera_id)

            start = time.monotonic()
            try:
                description = await self._vlm.describe(
                    job.frame,
                    job.detections,
                    job.provider,
                    system_prompt=job.system_prompt,
                    max_tokens=job.max_tokens,
                    heard_text=job.heard_text,
                    extra_context=job.extra_context,
                    max_input_tokens=job.max_input_tokens,
                )
                duration = time.monotonic() - start
                stats.record_latency(duration)

                if description:
                    # Save the exact frame the VLM looked at so the
                    # thumbnail stays in sync with the caption.
                    thumb_path = _write_vlm_thumbnail(
                        job.camera_id, job.observation_id, job.frame, job.detections,
                    )
                    # Patch observation with VLM description, thumbnail,
                    # and regenerate embedding.
                    await self._patch_observation(
                        job.observation_id, description, job.provider.name,
                        job.detections, thumbnail_path=thumb_path,
                    )
                    logger.info(
                        "VLM for camera %s completed in %.1fs. %s",
                        camera_id, duration, description[:80],
                    )
                    # Evaluate cascade triggers. Fires the refiner as a
                    # background task so the primary worker is free to
                    # take the next job. The refiner runs against the
                    # same frame + detections and replaces the row's
                    # vlm_description on success.
                    if self._should_refine(job, description):
                        asyncio.create_task(
                            self._run_refiner(job, description),
                            name=f"vlm-refiner-{camera_id[:8]}",
                        )
                else:
                    logger.warning("VLM returned empty for camera %s (%.1fs)", camera_id, duration)

            except Exception:
                duration = time.monotonic() - start
                stats.record_error()
                logger.exception(
                    "VLM call failed for camera %s after %.1fs", camera_id, duration,
                )

            # Update status based on latency
            if stats.avg_latency > 10:
                stats.status = "slow"
            else:
                stats.status = "processing" if not q.empty() else "idle"

            await self._broadcast_status(camera_id)

    @staticmethod
    def _should_refine(job: "VLMJob", primary_text: str) -> bool:
        """Decide whether the cascade refiner should fire for this job.

        Two cumulative gates.
        - YOLO labels in ``refiner_trigger_objects`` intersect the
          frame's detections.
        - keywords in ``refiner_keywords`` appear (case-insensitive)
          in the primary's text output.

        Either gate alone is enough. When both lists are empty we treat
        the refiner as 'always on'. The provider must be set; otherwise
        we never escalate.
        """
        if job.refiner_provider is None:
            return False
        labels = {str(x).lower() for x in (job.refiner_trigger_objects or [])}
        keywords = [str(k).strip().lower() for k in (job.refiner_keywords or []) if k]
        if not labels and not keywords:
            return True
        if labels:
            seen = {str(d.get("label", "")).lower() for d in (job.detections or [])}
            if seen & labels:
                return True
        if keywords and primary_text:
            text_lc = primary_text.lower()
            if any(k in text_lc for k in keywords):
                return True
        return False

    async def _run_refiner(self, job: "VLMJob", primary_text: str) -> None:
        """Call the refiner provider with the primary's output threaded
        into ``extra_context``. On success patch the observation row
        with the refined text and broadcast vlm_refined.
        """
        camera_id = job.camera_id
        provider = job.refiner_provider
        if provider is None:
            return
        # Stitch primary text into extra_context so the refiner can
        # treat it as a starting point. The base context (faces,
        # plates, location) carries through unchanged.
        primary_block = (
            f"Primary VLM said: \"{primary_text.strip()}\"."
            " Refine, correct, or expand it. Stay faithful to the"
            " visible scene and the identity / plate / location facts"
            " above. Return one cohesive description."
        )
        merged_context = (
            f"{job.extra_context.strip()} {primary_block}"
            if job.extra_context
            else primary_block
        )

        # Surface the refining state on the tile.
        stats = self._stats.get(camera_id)
        if stats is not None:
            prev_status = stats.status
            stats.status = "refining"
            await self._broadcast_status(camera_id)

        start = time.monotonic()
        try:
            refined = await self._vlm.describe(
                job.frame,
                job.detections,
                provider,
                system_prompt=job.system_prompt,
                max_tokens=job.refiner_max_tokens or job.max_tokens,
                heard_text=job.heard_text,
                extra_context=merged_context,
                max_input_tokens=job.refiner_max_input_tokens,
                camera_id=camera_id,
            )
            duration = time.monotonic() - start
            if not refined:
                logger.info(
                    "refiner returned empty camera=%s after %.1fs",
                    camera_id, duration,
                )
                return
            await self._patch_refiner_output(
                observation_id=job.observation_id,
                primary_text=primary_text,
                refined_text=refined,
                refiner_provider_name=provider.name,
                detections=job.detections,
            )
            logger.info(
                "refiner for camera %s completed in %.1fs. %s",
                camera_id, duration, refined[:80],
            )
            if self._broadcast_fn:
                try:
                    await self._broadcast_fn(
                        {
                            "type": "vlm_refined",
                            "camera_id": camera_id,
                            "observation_id": str(job.observation_id),
                            "primary_text": primary_text,
                            "refined_text": refined,
                            "refiner_provider_name": provider.name,
                            "duration_s": round(duration, 2),
                        }
                    )
                except Exception:
                    logger.debug("vlm_refined WS failed", exc_info=True)
        except Exception:
            logger.exception(
                "refiner call failed camera=%s observation=%s",
                camera_id, job.observation_id,
            )
        finally:
            if stats is not None:
                # Don't clobber a more interesting state set by another
                # job that ran while we were waiting on the refiner.
                if stats.status == "refining":
                    stats.status = prev_status if prev_status != "idle" else "idle"
                    await self._broadcast_status(camera_id)

    async def _patch_refiner_output(
        self,
        observation_id: uuid.UUID,
        primary_text: str,
        refined_text: str,
        refiner_provider_name: str,
        detections: list[dict],
    ) -> None:
        """Move primary's text into ``primary_vlm_description`` and put
        the refined text on the live ``vlm_description`` column.
        Regenerate the embedding because the description changed.
        """
        try:
            async with async_session() as db:
                obs = await db.get(Observation, observation_id)
                if obs is None:
                    return
                obs.primary_vlm_description = primary_text
                obs.vlm_description = refined_text
                obs.refined_by_provider_name = refiner_provider_name
                obs.refined_at = datetime.now(timezone.utc)
                await db.commit()
        except Exception:
            logger.exception("refiner observation patch failed obs=%s", observation_id)
            return
        try:
            parts = [refined_text]
            if detections:
                labels = [d["label"] for d in detections]
                parts.append("Objects detected. " + ", ".join(labels))
            embed_text = ". ".join(parts)
            embed_provider = await get_embedding_provider()
            embedding = await generate_embedding(embed_text, embed_provider)
            async with async_session() as db:
                obs = await db.get(Observation, observation_id)
                if obs is not None and embedding is not None:
                    obs.description_embedding = embedding
                    await db.commit()
        except Exception:
            logger.debug("refiner embedding regen failed", exc_info=True)

    async def _patch_observation(
        self, observation_id: uuid.UUID, description: str, provider_name: str,
        detections: list[dict], thumbnail_path: str | None = None,
    ):
        """Update observation record with VLM description and regenerate embedding."""
        try:
            async with async_session() as db:
                obs = await db.get(Observation, observation_id)
                if obs:
                    obs.vlm_description = description
                    obs.vlm_provider = provider_name
                    obs.confidence = 0.8
                    if thumbnail_path:
                        obs.thumbnail_path = thumbnail_path
                    await db.commit()
        except Exception:
            logger.exception("Failed to patch observation %s with VLM description", observation_id)
            return

        # Regenerate embedding now that VLM description is available
        try:
            parts = [description]
            if detections:
                labels = [d["label"] for d in detections]
                parts.append("Objects detected. " + ", ".join(labels))
            embed_text = ". ".join(parts)

            provider = await get_embedding_provider()
            embedding = await generate_embedding(embed_text, provider)

            async with async_session() as db:
                obs = await db.get(Observation, observation_id)
                if obs:
                    obs.description_embedding = embedding
                    await db.commit()
                    logger.debug("Regenerated embedding for observation %s with VLM description", observation_id)
        except Exception:
            logger.warning("Failed to regenerate embedding for observation %s", observation_id)

    async def _broadcast_status(self, camera_id: str):
        """Broadcast VLM status update via WebSocket."""
        if not self._broadcast_fn:
            return
        stats = self._stats.get(camera_id)
        if not stats:
            return
        try:
            await self._broadcast_fn({
                "type": "vlm_status",
                "camera_id": camera_id,
                "vlm": stats.to_dict(),
            })
        except Exception:
            pass  # don't let broadcast errors crash the worker

    async def shutdown(self):
        """Cancel all workers."""
        for task in self._workers.values():
            task.cancel()
        self._workers.clear()
