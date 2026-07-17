"""
Ingestion service entry point.

Manages RTSP stream connections, frame decoding, motion detection,
and segment recording for all configured cameras.
"""

import asyncio
import logging

from services.ingestion.manager import CameraManager
from services.ingestion.retention import RetentionManager
from shared import heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("nurby.ingestion")


async def main():
    logger.info("Starting Nurby ingestion service")
    manager = CameraManager()

    # Lets the doctor tell "this worker is dead" apart from "this user's
    # camera is broken". Without it a stopped ingestion service is
    # indistinguishable from a bad stream URL.
    asyncio.create_task(heartbeat.beat_forever(heartbeat.INGESTION))

    retention = RetentionManager()
    asyncio.create_task(retention.run())
    logger.info("Retention manager started as background task")

    await manager.run()


if __name__ == "__main__":
    asyncio.run(main())
