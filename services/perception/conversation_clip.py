"""Build a single mp4 clip covering a conversation window.

Called from the conversation finalizer after the summary VLM call
succeeds. Best-effort. when no overlapping recordings exist, or when
ffmpeg fails, the conversation row simply gets no clip_path and the
UI hides the video player.

Strategy.
- Find the Recording rows on the same camera that overlap
  [started_at, ended_at].
- Pick the one that covers the most of the window. Multi-segment
  concat is deferred; a single long recording is the common case for
  the recording_mode=always personas.
- ffmpeg -ss / -to trim with stream copy where possible. Falls back
  to re-encode if the cut point is not on a keyframe.
- Output to ``recordings/clips/<camera>/<conv_id>.mp4``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from shared.config import settings
from shared.database import async_session
from shared.models import Conversation, Recording

logger = logging.getLogger("nurby.perception.conversation_clip")


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def build_clip_for_conversation(
    conversation_id: uuid.UUID,
    camera_id: uuid.UUID,
    started_at: datetime,
    ended_at: datetime,
) -> tuple[str, int] | None:
    """Build the conversation clip and return (path, duration_ms) on
    success. Returns None when no source recording is available, the
    binary is missing, or ffmpeg returns non-zero.
    """
    if not _has_ffmpeg():
        logger.debug("ffmpeg not on PATH, skipping clip build")
        return None
    if ended_at <= started_at:
        return None

    rec = await _pick_overlapping_recording(camera_id, started_at, ended_at)
    if rec is None:
        return None
    src = _resolve_path(rec.file_path)
    if not src or not os.path.exists(src):
        return None

    rec_started = rec.started_at
    if rec_started.tzinfo is None:
        rec_started = rec_started.replace(tzinfo=timezone.utc)
    ss = max(0.0, (started_at - rec_started).total_seconds())
    duration_s = (ended_at - started_at).total_seconds()
    if duration_s <= 0:
        return None

    out_dir = os.path.join(
        os.path.abspath(settings.recordings_path),
        "clips",
        str(camera_id),
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{conversation_id}.mp4")

    # Attempt stream-copy first. Cuts that miss a keyframe will still
    # roughly work but may have a black opening; that's why we fall
    # back to re-encode when the result file is empty or absent.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-ss", f"{ss:.3f}",
        "-i", src,
        "-t", f"{duration_s:.3f}",
        "-c", "copy",
        "-movflags", "+faststart",
        out_path,
    ]
    rc = await _run_ffmpeg(cmd)
    if rc != 0 or not _file_ok(out_path):
        # Re-encode fallback. Slower but produces a valid mp4.
        logger.info(
            "stream-copy failed for conv %s, re-encoding", conversation_id
        )
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-ss", f"{ss:.3f}",
            "-i", src,
            "-t", f"{duration_s:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac",
            "-movflags", "+faststart",
            out_path,
        ]
        rc = await _run_ffmpeg(cmd)
        if rc != 0 or not _file_ok(out_path):
            logger.warning(
                "ffmpeg failed to build clip for conv %s (rc=%d)",
                conversation_id, rc,
            )
            try:
                os.remove(out_path)
            except FileNotFoundError:
                pass
            return None

    duration_ms = int(duration_s * 1000)
    logger.info(
        "conversation clip built. conv=%s file=%s dur_ms=%d size=%dB",
        conversation_id, out_path, duration_ms, os.path.getsize(out_path),
    )
    return out_path, duration_ms


async def _pick_overlapping_recording(
    camera_id: uuid.UUID,
    started_at: datetime,
    ended_at: datetime,
) -> Recording | None:
    """Pick the recording that covers the most of the conversation
    window. We do the overlap math in Python because the ranges are
    cheap and Recording.ended_at can be NULL while a clip is still
    being written.
    """
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Recording)
                .where(Recording.camera_id == camera_id)
                .where(Recording.started_at <= ended_at)
                .order_by(Recording.started_at.desc())
                .limit(20)
            )
        ).scalars().all()
    best: tuple[float, Recording] | None = None
    for r in rows:
        rec_start = r.started_at
        if rec_start.tzinfo is None:
            rec_start = rec_start.replace(tzinfo=timezone.utc)
        rec_end = r.ended_at or datetime.now(timezone.utc)
        if rec_end.tzinfo is None:
            rec_end = rec_end.replace(tzinfo=timezone.utc)
        if rec_end < started_at:
            continue
        overlap = (min(rec_end, ended_at) - max(rec_start, started_at)).total_seconds()
        if overlap <= 0:
            continue
        if best is None or overlap > best[0]:
            best = (overlap, r)
    return best[1] if best else None


def _resolve_path(stored: str | None) -> str | None:
    if not stored:
        return None
    if os.path.isabs(stored):
        return stored
    rel = stored
    for prefix in ("./recordings/", "recordings/", "./"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    return os.path.join(os.path.abspath(settings.recordings_path), rel)


def _file_ok(path: str) -> bool:
    try:
        return os.path.exists(path) and os.path.getsize(path) > 1024
    except OSError:
        return False


async def _run_ffmpeg(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 and stderr:
        logger.debug("ffmpeg stderr: %s", stderr.decode("utf-8", errors="ignore")[:500])
    return proc.returncode or 0


async def patch_conversation_clip(
    conversation_id: uuid.UUID,
    clip_path: str,
    duration_ms: int,
) -> None:
    try:
        async with async_session() as db:
            row = await db.get(Conversation, conversation_id)
            if row is None:
                return
            row.clip_path = clip_path
            row.clip_duration_ms = duration_ms
            await db.commit()
    except Exception:
        logger.exception("clip patch failed conv=%s", conversation_id)
