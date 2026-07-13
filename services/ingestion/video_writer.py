"""
Browser-playable segment writer.

cv2.VideoWriter with the "mp4v" fourcc produces MPEG-4 Part 2 video,
which no browser can decode -- every recording made that way plays as a
frozen black frame in the web UI (DEMUXER_ERROR_NO_SUPPORTED_STREAMS).
This module writes H.264 instead by piping raw BGR frames to an ffmpeg
subprocess, which is present everywhere ingestion runs (the webcam
bridge already shells out to it). If ffmpeg is unavailable the writer
falls back to cv2 "mp4v" so recording keeps working, and logs loudly so
the degradation is visible instead of silent.

Drop-in for the cv2.VideoWriter surface the stream worker uses:
``write(frame)`` and ``release()``.
"""

import logging
import shutil
import subprocess

import cv2

logger = logging.getLogger("nurby.ingestion.video_writer")

_ffmpeg_path: str | None = None
_ffmpeg_checked = False
_fallback_warned = False


def _find_ffmpeg() -> str | None:
    global _ffmpeg_path, _ffmpeg_checked
    if not _ffmpeg_checked:
        _ffmpeg_path = shutil.which("ffmpeg")
        _ffmpeg_checked = True
    return _ffmpeg_path


class H264SegmentWriter:
    """Pipe BGR frames into ffmpeg producing an H.264 MP4 segment.

    ``+faststart`` relocates the moov atom so partially downloaded
    segments start playing immediately in the browser player.
    """

    def __init__(self, path: str, fps: float, width: int, height: int):
        ffmpeg = _find_ffmpeg()
        if ffmpeg is None:
            raise FileNotFoundError("ffmpeg not found on PATH")
        self._proc = subprocess.Popen(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-s", f"{width}x{height}",
                "-r", f"{fps:.6f}",
                "-i", "pipe:0",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                path,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._path = path
        self._failed = False

    def isOpened(self) -> bool:  # noqa: N802 - mirrors cv2.VideoWriter
        return not self._failed and self._proc.poll() is None

    def write(self, frame) -> None:
        if self._failed or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(frame.tobytes())
        except (BrokenPipeError, OSError):
            # Encoder died mid-segment. Capture stderr once on release.
            self._failed = True

    def _reap(self) -> None:
        try:
            self._proc.kill()
            self._proc.wait(timeout=10)
        except Exception:
            logger.exception("Failed to reap ffmpeg encoder (%s)", self._path)

    def release(self) -> None:
        stderr = b""
        try:
            # communicate() flushes + closes stdin (the encoder's EOF),
            # waits for exit, and drains stderr. Don't close stdin
            # manually first: communicate() then flushes a closed file
            # and dies with ValueError mid-setup.
            _, stderr = self._proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            self._reap()
            logger.error("ffmpeg segment encoder hung; killed (%s)", self._path)
        except (ValueError, OSError):
            # stdin already broken (encoder died mid-segment). Reap the
            # process; stderr was captured up to the failure.
            self._reap()
        if self._failed or self._proc.returncode not in (0, None):
            logger.error(
                "ffmpeg segment encoder failed for %s (rc=%s): %s",
                self._path,
                self._proc.returncode,
                (stderr or b"").decode(errors="replace")[-500:],
            )


def create_segment_writer(path: str, fps: float, width: int, height: int):
    """Return the best available segment writer for ``path``.

    Prefers the H.264 ffmpeg pipe; falls back to cv2 "mp4v" (not
    browser-playable) only when ffmpeg is missing, warning once.
    """
    global _fallback_warned
    if not fps or fps != fps or fps <= 0 or fps > 240:
        fps = 24.0
    try:
        return H264SegmentWriter(path, fps, width, height)
    except FileNotFoundError:
        if not _fallback_warned:
            logger.warning(
                "ffmpeg not found. Falling back to cv2 mp4v recording, which "
                "browsers cannot play. Install ffmpeg to get H.264 recordings."
            )
            _fallback_warned = True
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        return cv2.VideoWriter(path, fourcc, fps, (width, height))
