"""Periodic driver for auto Home/Away mode (#184).

Runs :func:`services.perception.presence_mode.evaluate_and_apply` on a slow
loop so household mode tracks who is home without any per-frame cost. Slow on
purpose: presence changes on a minutes scale, and a manual tap wins for a
grace window regardless.
"""

from __future__ import annotations

import asyncio
import logging

from shared.database import async_session

logger = logging.getLogger("nurby.perception.presence_mode")

INTERVAL_SECONDS = 120


class PresenceModeSweeper:
    def __init__(self, interval_seconds: int = INTERVAL_SECONDS) -> None:
        self._interval = interval_seconds
        self._running = False

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                async with async_session() as db:
                    from services.perception.presence_mode import evaluate_and_apply

                    changed = await evaluate_and_apply(db)
                    if changed:
                        logger.info("auto household mode -> %s", changed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("presence-mode sweep failed; retrying next cycle")
            await asyncio.sleep(self._interval)
