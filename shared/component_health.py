"""Functional component health, beyond bare worker liveness.

The worker heartbeats (shared/heartbeat) answer "is the process running?".
They do NOT answer "is the process actually producing anything?". A worker
can heartbeat happily while every observation write crashes (a model/DB
drift), or while the clap tagger silently failed to load its model, so the
doctor read green while the pipeline produced nothing. This module lets a
component publish its real state so the doctor (and dashboard) can surface a
functional outage, not just a dead process.

Each component writes ``nurby:health:<component>`` = JSON{status, detail, ts}.
- ``ok``   : working. Refreshed on each success.
- ``fail`` : broken. Set on error, with a human detail.
A TTL means "no news in a while" reads as unknown/idle rather than a stale
verdict. A load-once component (the audio tagger) sets no TTL: its verdict
holds until the process restarts and re-reports.
"""

import json
import logging

from shared.clock import stamp_now
from shared.config import settings

logger = logging.getLogger("nurby.component_health")

# Component ids. Keep in sync with the doctor's checks.
AUDIO_TAGGER = "audio_tagger"          # PANNs clap / sound-event model
OBSERVATION_WRITER = "observation_writer"  # perception -> observations table
VLM = "vlm"                            # vision-language captioning

OK = "ok"
FAIL = "fail"

# Frequently-updated components (observation writes, VLM captions) expire so a
# quiet system reads as idle, not stale-broken. A recent FAIL still means
# broken. Load-once components pass ttl=None for a verdict that persists.
DEFAULT_TTL_SECONDS = 900


def _key(component: str) -> str:
    return f"nurby:health:{component}"


def _payload(status: str, detail: str | None) -> str:
    return json.dumps(
        {"status": status, "detail": (detail or "")[:300], "ts": stamp_now().isoformat()}
    )


async def report(
    component: str, status: str, detail: str | None = None, ttl: int | None = DEFAULT_TTL_SECONDS
) -> None:
    """Async publish. Never raises: health reporting must not break the
    thing it is reporting on."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.set(_key(component), _payload(status, detail), ex=ttl)
        finally:
            await client.aclose()
    except Exception:
        logger.debug("component health report failed for %s", component, exc_info=True)


def report_sync(
    component: str, status: str, detail: str | None = None, ttl: int | None = DEFAULT_TTL_SECONDS
) -> None:
    """Sync publish, for non-async call sites (e.g. the tagger loading in a
    worker thread). Never raises."""
    try:
        import redis

        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            client.set(_key(component), _payload(status, detail), ex=ttl)
        finally:
            client.close()
    except Exception:
        logger.debug("component health report failed for %s", component, exc_info=True)


async def get(component: str) -> dict | None:
    """Read a component's last reported health, or None if it has never
    reported (or its report expired)."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            raw = await client.get(_key(component))
        finally:
            await client.aclose()
        return json.loads(raw) if raw else None
    except Exception:
        logger.debug("component health read failed for %s", component, exc_info=True)
        return None
