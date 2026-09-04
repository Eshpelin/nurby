"""Vendor HTTP two-way audio (issue #155).

For cameras that have a speaker but do not offer the ONVIF backchannel,
which is a large fraction of the consumer market. Each vendor exposes its
own endpoint; the shape is always "open a channel, push raw audio, close
it", so the difference between them is a handful of strings.

Sharing a base class rather than a copy per vendor keeps the auth, the
error handling and the streaming identical, so a fix to one is a fix to
all. Adding a vendor is a subclass with three attributes.

All of these need digest auth in practice. See services/voice/auth.py.
"""

from __future__ import annotations

import logging

import httpx

from services.voice.auth import digest_response, parse_challenge
from services.voice.transport import TransportError, TransportUnsupported

logger = logging.getLogger("nurby.voice.transport.vendor")

DEFAULT_TIMEOUT = 15.0


def camera_base_url(camera) -> str:
    """The camera's HTTP base, derived from its RTSP stream URL. Pure.

    Cameras are configured by their stream URL and rarely carry a
    separate HTTP address, so it is derived rather than asked for again.
    Port 80 is assumed because the RTSP port (554) is never the HTTP one.
    """
    from urllib.parse import urlparse

    parsed = urlparse(getattr(camera, "stream_url", "") or "")
    host = parsed.hostname
    if not host:
        raise TransportUnsupported("camera has no resolvable host")
    port = getattr(camera, "http_port", None) or 80
    scheme = "https" if int(port) == 443 else "http"
    return f"{scheme}://{host}:{int(port)}"


class _VendorTransport:
    """Open a channel, push audio, close it."""

    kind = "vendor"
    name = "vendor two-way audio"
    # Subclasses fill these in.
    open_path: str | None = None
    audio_path: str = ""
    close_path: str | None = None
    content_type = "application/octet-stream"
    method = "PUT"

    def content_type_for(self, codec: str) -> str:
        return self.content_type

    async def speak(self, camera, payload: bytes, *, codec: str,
                    sample_rate: int, volume: int = 70,
                    timeout: float = DEFAULT_TIMEOUT) -> None:
        from shared.camera_secrets import unseal

        base = camera_base_url(camera)
        username = getattr(camera, "username", None) or ""
        try:
            password = unseal(getattr(camera, "password", None)) or ""
        except Exception:
            password = ""

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            if self.open_path:
                await self._send(client, base, self.open_path, username,
                                 password, method="PUT", body=b"")
            try:
                await self._send(
                    client, base, self.audio_path, username, password,
                    method=self.method, body=payload,
                    content_type=self.content_type_for(codec),
                )
            finally:
                # Always close. A channel left open blocks the next
                # utterance on most of these cameras, so a failure here
                # would make the first error permanent.
                if self.close_path:
                    try:
                        await self._send(client, base, self.close_path,
                                         username, password, method="PUT", body=b"")
                    except Exception:
                        logger.debug("closing audio channel failed", exc_info=True)

    async def _send(self, client, base: str, path: str, username: str,
                    password: str, *, method: str, body: bytes,
                    content_type: str | None = None) -> None:
        url = f"{base}{path}"
        headers = {"Content-Type": content_type or self.content_type}

        response = await client.request(method, url, content=body, headers=headers)
        if response.status_code == 401 and username:
            challenge = parse_challenge(
                response.headers.get("www-authenticate", "")
            )
            auth = digest_response(
                username=username, password=password, method=method,
                uri=path, challenge=challenge,
            )
            if not auth:
                raise TransportError("camera requires an auth scheme we do not speak")
            headers["Authorization"] = auth
            response = await client.request(
                method, url, content=body, headers=headers
            )

        if response.status_code == 401:
            raise TransportError("camera rejected our credentials")
        if response.status_code == 404:
            raise TransportUnsupported(
                f"{self.name} endpoint not present on this camera"
            )
        if response.status_code >= 400:
            raise TransportError(
                f"{self.name} returned HTTP {response.status_code}"
            )


class HikvisionTransport(_VendorTransport):
    """Hikvision ISAPI two-way audio.

    Open the channel, PUT raw G.711 to audioData, close it. Channel 1 is
    the built-in speaker on every unit seen; multi-channel NVRs would
    need the channel to come from configuration.
    """

    kind = "hikvision"
    name = "Hikvision two-way audio"
    open_path = "/ISAPI/System/TwoWayAudio/channels/1/open"
    audio_path = "/ISAPI/System/TwoWayAudio/channels/1/audioData"
    close_path = "/ISAPI/System/TwoWayAudio/channels/1/close"
    content_type = "application/octet-stream"


class DahuaTransport(_VendorTransport):
    """Dahua (and Amcrest) CGI two-way audio.

    One POST carrying the whole stream, with the codec in the content
    type rather than in a separate negotiation, which is why
    content_type_for is overridden here.
    """

    kind = "dahua"
    name = "Dahua two-way audio"
    open_path = None
    audio_path = "/cgi-bin/audio.cgi?action=postAudio&httptype=singlepart&channel=1"
    close_path = None
    method = "POST"

    def content_type_for(self, codec: str) -> str:
        return {
            "pcmu": "Audio/G.711U",
            "pcma": "Audio/G.711A",
        }.get((codec or "").lower(), "Audio/G.711A")
