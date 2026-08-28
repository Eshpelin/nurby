"""Shared audio types for the voice path.

Deliberately small and provider-agnostic: a clip is raw PCM plus the
three facts needed to interpret it. Everything downstream (resampling,
codec conversion, transport) works off this rather than off whatever
shape a particular TTS engine happens to emit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioClip:
    """Raw PCM audio. ``pcm`` is signed little-endian samples."""

    pcm: bytes
    sample_rate: int
    channels: int = 1
    sample_width: int = 2  # bytes per sample, 2 = 16-bit

    @property
    def frame_count(self) -> int:
        stride = self.sample_width * self.channels
        return len(self.pcm) // stride if stride else 0

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate if self.sample_rate else 0.0
