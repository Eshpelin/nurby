#!/usr/bin/env python3
"""Probe every camera for speaker capability (issue #153).

    python scripts/probe_speakers.py            # probe all, print a table
    python scripts/probe_speakers.py --save     # also record the findings
    python scripts/probe_speakers.py --camera <id>

Read-only by default. ``--save`` writes a SpeakerCapability row per
camera, including for the ones that cannot speak: "we looked and it
cannot" is a finding the UI needs, and is different from "we never
looked".
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.voice.probe import probe_camera, store_result  # noqa: E402
from shared.database import async_session  # noqa: E402
from shared.models import Camera  # noqa: E402


def _row(name: str, result) -> str:
    verdict = "YES" if result.supported else "no"
    detail = result.codec or result.error or ""
    return (
        f"{name[:24]:<24} {result.vendor or '-':<10} "
        f"{result.transport:<20} {verdict:<4} {detail[:44]}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", help="probe only this camera id")
    parser.add_argument("--save", action="store_true",
                        help="record the findings in speaker_capabilities")
    parser.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()

    async with async_session() as db:
        query = select(Camera)
        if args.camera:
            query = query.where(Camera.id == uuid.UUID(args.camera))
        cameras = list((await db.execute(query)).scalars().all())

        if not cameras:
            print("no cameras configured")
            return 0

        print(f"{'CAMERA':<24} {'VENDOR':<10} {'TRANSPORT':<20} {'CAN':<4} DETAIL")
        print("-" * 104)

        supported = 0
        for camera in cameras:
            result = await probe_camera(camera, timeout=args.timeout)
            print(_row(camera.name, result))
            supported += 1 if result.supported else 0
            if args.save:
                await store_result(db, camera.id, result)

        if args.save:
            await db.commit()

        print("-" * 104)
        print(f"{supported} of {len(cameras)} camera(s) can be spoken through")
        if not args.save:
            print("(nothing recorded; re-run with --save to store these findings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
