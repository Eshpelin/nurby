"""Piper TTS. The local default (issue #154).

Piper is a small neural TTS that runs on CPU faster than real time, which
is what makes a fully local voice practical on the same machine that is
already decoding video. It reads text on stdin and writes a WAV on
stdout, so the integration is a subprocess rather than a library, in the
same shape as ``services/ingestion/webcam_bridge.py``.

Absence is not an error here. A household that has not installed Piper
should get a clear "voice is not available" rather than a stack trace at
rule-fire time, so the provider reports itself unavailable and the caller
decides. That mirrors how body re-id treats a missing torch.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import struct

from services.voice.types import AudioClip

logger = logging.getLogger("nurby.voice.piper")

# Long enough for a paragraph on a slow CPU, short enough that a hung
# binary cannot hold a rule action open.
SYNTHESIS_TIMEOUT_SECONDS = 30.0


class PiperUnavailable(RuntimeError):
    """Piper is not installed, or its model is missing."""


def parse_wav(payload: bytes) -> AudioClip:
    """Minimal RIFF/WAVE reader for what Piper emits. Pure, for tests.

    Deliberately not ``wave``: that module wants a seekable file object,
    and this arrives as bytes on a pipe. Piper always writes 16-bit mono
    PCM, so only that case has to work, and anything else is rejected
    loudly rather than misread.
    """
    if len(payload) < 44 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE payload")

    pos = 12
    fmt = None
    while pos + 8 <= len(payload):
        chunk_id = payload[pos:pos + 4]
        (size,) = struct.unpack_from("<I", payload, pos + 4)
        body = payload[pos + 8:pos + 8 + size]
        if chunk_id == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body, 0)
        elif chunk_id == b"data":
            if fmt is None:
                raise ValueError("data chunk before fmt chunk")
            _, channels, rate, _, _, bits = fmt
            if bits != 16:
                raise ValueError(f"expected 16-bit PCM, got {bits}-bit")
            return AudioClip(bytes(body), rate, channels, 2)
        # Chunks are word-aligned; an odd size carries a pad byte.
        pos += 8 + size + (size & 1)
    raise ValueError("no data chunk in WAVE payload")


class PiperProvider:
    kind = "piper"
    is_local = True

    def __init__(self, model: str = "en_US-amy-medium",
                 binary: str | None = None, model_path: str | None = None):
        self.model = model
        self.name = f"piper {model}"
        self.binary = binary or "piper"
        self.model_path = model_path

    def available(self) -> bool:
        """Whether Piper can actually run. Cheap enough to call before
        every synthesis, and honest when the answer is no."""
        return shutil.which(self.binary) is not None

    async def synthesize(self, text: str, voice: str | None = None) -> AudioClip:
        if not self.available():
            raise PiperUnavailable(
                f"{self.binary!r} is not on PATH. install Piper, or configure "
                "another voice_tts_provider"
            )

        cmd = [self.binary, "--output_file", "-"]
        model_path = voice or self.model_path
        if model_path:
            cmd += ["--model", model_path]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise PiperUnavailable(f"could not start {self.binary!r}: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(text.encode("utf-8")),
                timeout=SYNTHESIS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise PiperUnavailable("piper timed out") from None

        if proc.returncode != 0:
            detail = (stderr or b"").decode("utf-8", "replace").strip()[:200]
            raise PiperUnavailable(f"piper exited {proc.returncode}: {detail}")

        return parse_wav(stdout)
