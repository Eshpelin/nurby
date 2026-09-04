"""TP-Link Tapo two-way audio. Not implemented, deliberately (#155).

Tapo cameras speak ONVIF for discovery and RTSP for video, but their
two-way audio runs over a proprietary authenticated HTTPS API: a login
handshake yielding a session token, then an audio channel opened through
that session. It is reverse-engineered rather than documented, and the
handshake has changed across firmware versions.

This exists as a named transport so the probe and the UI can say
"supported by this camera, not yet by us", which is a different and more
useful statement than "unsupported". Implementing it is its own piece of
work with its own hardware requirement.
"""

from __future__ import annotations

from services.voice.transport import TransportUnsupported, register_factory


class TapoTransport:
    kind = "tapo"
    name = "Tapo two-way audio"

    async def speak(self, camera, payload: bytes, *, codec: str,
                    sample_rate: int, volume: int = 70,
                    timeout: float = 15.0) -> None:
        raise TransportUnsupported(
            "Tapo two-way audio uses a proprietary API that Nurby does not "
            "speak yet. Point this camera at an external speaker endpoint "
            "instead, or use a camera with an ONVIF backchannel."
        )


async def _factory() -> TapoTransport:
    return TapoTransport()


register_factory("tapo", _factory)
