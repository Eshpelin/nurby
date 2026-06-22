"""Background sweeper that expires overdue sequence-rule instances.

Mirrors the other housekeeping loops (reid_sweeper, face_merger). Every
`sequence_sweep_interval_seconds` it marks active instances whose current step
deadline has lapsed as `expired`, so they stop advancing and don't accumulate.
Firing the `on_timeout` action chain on expiry is slice 2.
"""

import asyncio
import logging

from services.events import sequences

logger = logging.getLogger("nurby.events.sequence_sweeper")


class SequenceSweeper:
    def __init__(self) -> None:
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        from shared.app_settings import get_setting

        while not self._stopping.is_set():
            try:
                n = await sequences.expire_due()
                if n:
                    logger.info("expired %d overdue sequence instance(s)", n)
            except Exception:
                logger.exception("sequence sweeper tick failed")
            try:
                interval = int(await get_setting("sequence_sweep_interval_seconds", 15))
            except Exception:
                interval = 15
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(5, interval))
            except asyncio.TimeoutError:
                pass
