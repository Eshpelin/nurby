"""An external speaker that is not the camera (issue #155).

The path that always works. A household whose cameras have no speaker, or
whose cameras only offer a proprietary API nobody has written a driver
for yet, can point a camera at any HTTP endpoint that accepts audio: a
Raspberry Pi with a speaker, a media player, a smart speaker bridge.

Reuses the shape of the existing ``Device`` action rather than inventing
configuration: an endpoint on the camera row, the audio as the body. That
keeps "Nurby can speak here" true for every household rather than only
the ones who bought the right cameras.
"""

from __future__ import annotations

import logging

import httpx

from services.voice.transport import TransportError, TransportUnsupported

logger = logging.getLogger("nurby.voice.transport.device")


class HttpDeviceTransport:
    kind = "http_device"
    name = "external speaker"

    async def speak(self, camera, payload: bytes, *, codec: str,
                    sample_rate: int, volume: int = 70,
                    timeout: float = 15.0) -> None:
        from shared.camera_secrets import unseal

        endpoint = getattr(camera, "speaker_endpoint", None)
        if not endpoint:
            raise TransportUnsupported(
                "no external speaker endpoint configured for this camera"
            )
        try:
            endpoint = unseal(endpoint) or endpoint
        except Exception:
            pass

        headers = {
            "Content-Type": f"audio/{'basic' if codec == 'pcmu' else 'x-alaw-basic'}",
            # Passed along so a receiver can resample or set its own
            # level without having to guess what it was sent.
            "X-Nurby-Codec": codec,
            "X-Nurby-Sample-Rate": str(sample_rate),
            "X-Nurby-Volume": str(volume),
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, content=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise TransportError(f"external speaker unreachable: {exc}") from exc

        if response.status_code >= 400:
            raise TransportError(
                f"external speaker returned HTTP {response.status_code}"
            )
