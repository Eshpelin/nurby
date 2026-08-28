"""A TTS provider that produces correctly shaped audio and no speech.

Every test in the voice path needs a clip of the right length, sample
rate and sample width, and none of them need it to be intelligible.
Mirrors ``audio/providers/mock_provider.py`` on the STT side.
"""

from __future__ import annotations

import array
import math

from services.voice.types import AudioClip

# Roughly conversational pace. Used to give a mock clip a duration that
# scales with its text, so a test asserting "the speaker was busy for
# about this long" is exercising something real.
CHARS_PER_SECOND = 14.0


class MockTTSProvider:
    kind = "mock"
    is_local = True

    def __init__(self, model: str = "mock", sample_rate: int = 22050,
                 tone_hz: float = 0.0):
        self.model = model
        self.name = f"mock tts ({model})"
        self.sample_rate = sample_rate
        # 0 renders silence. A tone is useful when a human wants to hear
        # that the transport actually played something.
        self.tone_hz = tone_hz

    async def synthesize(self, text: str, voice: str | None = None) -> AudioClip:
        seconds = max(0.1, len(text) / CHARS_PER_SECOND)
        frames = int(self.sample_rate * seconds)
        if self.tone_hz > 0:
            samples = array.array("h", [
                int(12000 * math.sin(2 * math.pi * self.tone_hz * i / self.sample_rate))
                for i in range(frames)
            ])
        else:
            samples = array.array("h", bytes(frames * 2))
        return AudioClip(samples.tobytes(), self.sample_rate, 1, 2)
