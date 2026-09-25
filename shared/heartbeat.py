"""Worker liveness heartbeats.

The ingestion and perception workers are where all the real work happens,
but nothing ever asked whether they were running. When they weren't, the
symptom surfaced as a camera that "sat offline" and a dashboard that said
"Nothing happened yet" - and the doctor blamed the user's stream URL and
credentials, sending them to debug a camera that was fine. A dead worker
and a broken camera looked identical.

Each worker writes a key with a TTL and re-writes it on a timer. If the
worker dies, the key expires and it is unambiguously down. There is no
clock arithmetic and no state to clean up, which also means a worker that
hangs (rather than exits) still stops beating and is still reported down.
"""

import asyncio
import logging

from shared.clock import stamp_now
from shared.config import settings
from shared.redis_keys import LEGACY_HEARTBEAT_PREFIX, heartbeat_key

logger = logging.getLogger("nurby.heartbeat")

INGESTION = "ingestion"
PERCEPTION = "perception"

# Beat well inside the TTL so one slow loop or a brief redis blip doesn't
# flap a healthy worker to "down".
BEAT_INTERVAL_SECONDS = 10
TTL_SECONDS = 35


def _key(service: str) -> str:
    return heartbeat_key(service)


def _read_keys(service: str) -> tuple[str, str]:
    """Namespaced key first, legacy key as a one-release fallback (#291).

    A just-updated stack reads workers' first beats only after the new
    write lands; without the fallback the doctor would flap to "down"
    for up to one TTL after every update."""
    return (heartbeat_key(service), f"{LEGACY_HEARTBEAT_PREFIX}{service}")


async def beat_forever(service: str) -> None:
    """Re-write ``service``'s heartbeat key until cancelled.

    Never raises: a worker must not die because redis hiccuped. A failed
    beat just means the key expires and the service reads as down, which
    is the honest answer while redis is unreachable anyway.
    """
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            try:
                await client.set(_key(service), stamp_now().isoformat(), ex=TTL_SECONDS)
            except Exception:
                logger.warning("heartbeat write failed for %s", service, exc_info=True)
            await asyncio.sleep(BEAT_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    finally:
        await client.aclose()


async def last_beat(service: str) -> str | None:
    """ISO timestamp of ``service``'s last heartbeat, or None if it is not
    running (or redis is unreachable, which the caller checks separately)."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    primary, legacy = _read_keys(service)
    try:
        value = await client.get(primary)
        if value is None:
            value = await client.get(legacy)
        return value
    finally:
        await client.aclose()


async def is_alive(service: str) -> bool:
    try:
        return (await last_beat(service)) is not None
    except Exception:
        return False
