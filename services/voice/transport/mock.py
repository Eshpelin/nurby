"""A transport that records what it was asked to play, and plays nothing.

Every test above the driver layer needs to assert that the right audio
reached the right camera, and none of them need a speaker.
"""

from __future__ import annotations

from services.voice.transport import SpeakerTransport, TransportError


class MockTransport:
    kind = "mock"
    name = "mock speaker"

    def __init__(self):
        self.played: list[dict] = []
        # Set to raise on the next call, for exercising failure paths.
        self.fail_with: str | None = None

    async def speak(self, camera, payload: bytes, *, codec: str,
                    sample_rate: int, volume: int = 70, timeout: float = 15.0) -> None:
        if self.fail_with:
            raise TransportError(self.fail_with)
        self.played.append({
            "camera_id": getattr(camera, "id", None),
            "bytes": len(payload),
            "codec": codec,
            "sample_rate": sample_rate,
            "volume": volume,
        })
