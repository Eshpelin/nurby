"""VLM failure is surfaced, not swallowed.

The per-camera worker used to drop silently back to idle when a VLM call
errored, timed out, or returned nothing. The dashboard "Analyzing" shimmer
then just vanished with no "couldn't analyze" feedback. These tests pin the
explicit ``status: "failed"`` signal (plus a short reason) that now goes out
over the same ``vlm_status`` WebSocket channel.
"""

import asyncio
import types
import uuid
from datetime import datetime, timezone

import numpy as np

from services.perception.vlm_queue import CameraVLMStats, VLMJob, VLMQueue


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _job(camera_id: str) -> VLMJob:
    return VLMJob(
        camera_id=camera_id,
        observation_id=uuid.uuid4(),
        frame=np.zeros((4, 4, 3), dtype=np.uint8),
        detections=[],
        provider=types.SimpleNamespace(name="fake", kind="anthropic"),
        system_prompt=None,
        max_tokens=None,
        timestamp=datetime.now(timezone.utc),
    )


class _FakeVLM:
    """Stand-in VLM client with a configurable describe() behaviour."""

    def __init__(self, behaviour):
        self._behaviour = behaviour

    async def describe(self, *args, **kwargs):
        return await self._behaviour()


async def _drive_one_job(behaviour) -> list[dict]:
    """Run a single failing job through the in-memory worker and return the
    ordered list of vlm_status payloads broadcast for the camera."""
    cam = "cam-fail"
    q = VLMQueue(vlm_client=_FakeVLM(behaviour))

    seen: list[dict] = []

    async def broadcast(msg):
        if msg.get("type") == "vlm_status" and msg.get("camera_id") == cam:
            seen.append(msg["vlm"])

    q.set_broadcast(broadcast)
    # Worker reads stats[cam] up front and pulls jobs from the in-mem queue.
    q._stats[cam] = CameraVLMStats()
    queue = q._queues.setdefault(cam, asyncio.Queue(maxsize=4))
    await queue.put(_job(cam))

    worker = asyncio.create_task(q._worker(cam))
    # Poll until a terminal status lands, then stop the worker.
    for _ in range(200):
        await asyncio.sleep(0.01)
        if any(v["status"] in ("idle", "processing", "slow") for v in seen) and any(
            v["status"] == "failed" for v in seen
        ):
            break
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass
    return seen


def test_empty_description_emits_failed_status():
    async def empty():
        return None

    seen = _run(_drive_one_job(empty))
    failed = [v for v in seen if v["status"] == "failed"]
    assert failed, f"expected a failed vlm_status, got {[v['status'] for v in seen]}"
    assert failed[0]["reason"] == "no description returned"
    assert failed[0]["total_errors"] == 1


def test_timeout_emits_failed_status():
    async def hang():
        await asyncio.sleep(999)

    # Shrink the worker timeout so the test does not actually wait.
    import services.perception.vlm_queue as vq

    orig = vq.VLM_CALL_TIMEOUT_SECONDS
    vq.VLM_CALL_TIMEOUT_SECONDS = 0.05
    try:
        seen = _run(_drive_one_job(hang))
    finally:
        vq.VLM_CALL_TIMEOUT_SECONDS = orig

    failed = [v for v in seen if v["status"] == "failed"]
    assert failed, f"expected a failed vlm_status, got {[v['status'] for v in seen]}"
    assert failed[0]["reason"] == "analysis timed out"


def test_exception_emits_failed_status():
    async def boom():
        raise RuntimeError("provider exploded")

    seen = _run(_drive_one_job(boom))
    failed = [v for v in seen if v["status"] == "failed"]
    assert failed, f"expected a failed vlm_status, got {[v['status'] for v in seen]}"
    assert failed[0]["reason"] == "analysis error"


def test_failed_status_clears_to_idle_for_next_frame():
    """The failure is a one-shot signal: the trailing status update resets to
    idle (no backlog) so a later success starts clean."""

    async def empty():
        return None

    seen = _run(_drive_one_job(empty))
    assert seen[-1]["status"] == "idle"
    assert seen[-1]["reason"] == ""


def test_update_status_never_overwrites_failed():
    stats = CameraVLMStats()
    stats.avg_latency = 50.0  # would normally force "slow"
    stats.record_error("analysis error")
    assert stats.status == "failed"
    out = stats.to_dict()
    assert out["status"] == "failed"
    assert out["reason"] == "analysis error"
