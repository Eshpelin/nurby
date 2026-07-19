"""Camera availability watcher.

Consumes offline/online edges from the ``nurby:camera_status`` Redis stream
(published by ingestion's StreamWorker on real status transitions) and runs
them through the rule engine, so ``camera_offline`` and ``camera_online``
triggers fire. This is the path that makes "alert me when a camera goes
dark" possible at all: an offline camera produces no observations, so the
observation-driven evaluate loop can never see it.

Uses a consumer group, like the motion pipeline, so an edge that lands
while perception restarts is processed on the way back up instead of lost.
"""

import asyncio
import logging

import redis.asyncio as aioredis
from redis.exceptions import TimeoutError as RedisTimeoutError

from shared.redis_keys import CAMERA_STATUS_STREAM_KEY
from shared.config import settings

logger = logging.getLogger("nurby.perception.camera_status")

CONSUMER_GROUP = "perception-camera-status"
CONSUMER_NAME = "camera-status-watcher"
BLOCK_MS = 5000


class CameraStatusWatcher:
    """Feed camera availability edges through a shared RuleEngine."""

    def __init__(self, rule_engine):
        self._rule_engine = rule_engine
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _to_event(fields: dict) -> dict:
        """Shape a stream entry into the rule engine's data dict.

        ``event_kind`` is the marker _match_trigger keys on so these
        payloads only ever match camera_offline / camera_online rules.
        """
        return {
            "event_kind": "camera_status",
            "camera_id": fields.get("camera_id") or None,
            "camera_name": fields.get("camera_name") or "",
            "camera_status": fields.get("camera_status") or "",
            "previous_status": fields.get("previous_status") or None,
            "status_reason": fields.get("reason") or "",
            "timestamp": fields.get("timestamp") or "",
        }

    async def run(self):
        r = await self._get_redis()
        try:
            await r.xgroup_create(
                CAMERA_STATUS_STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
            )
            logger.info("Created consumer group '%s'", CONSUMER_GROUP)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        logger.info("Watching camera availability on '%s'", CAMERA_STATUS_STREAM_KEY)

        while True:
            try:
                messages = await r.xreadgroup(
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    {CAMERA_STATUS_STREAM_KEY: ">"},
                    count=10,
                    block=BLOCK_MS,
                )
                if not messages:
                    continue
                for _stream, entries in messages:
                    for msg_id, fields in entries:
                        try:
                            await self._rule_engine.evaluate(self._to_event(fields))
                        except Exception:
                            logger.exception(
                                "camera status rule evaluation failed for %s", msg_id
                            )
                        finally:
                            await r.xack(CAMERA_STATUS_STREAM_KEY, CONSUMER_GROUP, msg_id)
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, RedisTimeoutError):
                # Expected idle case: the blocking read hit its socket timeout
                # with no new status events. Not an error. Loop straight back
                # into xreadgroup so a real event is still picked up promptly.
                continue
            except Exception:
                logger.exception("camera status watcher loop error; retrying in 5s")
                await asyncio.sleep(5)
