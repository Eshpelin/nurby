"""ONVIF Profile T audio backchannel over RTSP (issue #155).

The only vendor-neutral way to speak through a camera, and therefore the
one worth getting right: Hikvision, Dahua, Axis, Reolink, Uniview and
most ONVIF-conformant units implement it, so a single correct driver
covers far more households than any number of vendor integrations.

The session is a normal RTSP handshake with one twist. Every request
carries ``Require: www.onvif.org/ver20/backchannel``, which asks the
camera to include a media section we are allowed to send on, and the
audio then flows *up* the same TCP connection using RTSP's interleaved
framing.

    DESCRIBE  -> SDP with an a=sendonly audio section
    SETUP     -> on that section's control URL, interleaved channels
    RECORD    -> start the session
    ...RTP... -> paced at real time, 20 ms per packet
    TEARDOWN  -> always, even on failure

Two details that are easy to get wrong and painful to debug:

**Direction.** SDP directions in an RTSP answer are written from the
client's point of view, so the camera's microphone is ``a=recvonly`` and
the speaker channel we want is ``a=sendonly``. Selecting the wrong one
pushes audio at a track that never plays it, with no error anywhere.

**Pacing.** RTP is a real-time protocol and cameras have small jitter
buffers. Writing every packet as fast as the socket accepts them
overflows the buffer and produces a fraction of a second of noise
followed by silence, so packets are paced to their own duration.

Interleaved TCP rather than UDP throughout: it needs no second socket, no
inbound port, and it works through the NAT and firewall arrangements a
household actually has.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

from services.voice import rtp
from services.voice.auth import digest_response, parse_challenge
from services.voice.probe import (
    ONVIF_BACKCHANNEL,
    parse_backchannel_sdp,
    rtsp_status,
    split_response,
)
from services.voice.transport import TransportError, TransportUnsupported

logger = logging.getLogger("nurby.voice.transport.onvif")

DEFAULT_TIMEOUT = 15.0

# Interleaved channel numbers for the backchannel. 0 and 1 are the
# conventional first pair (RTP and RTCP).
RTP_CHANNEL = 0
RTCP_CHANNEL = 1


class _Session:
    """One RTSP control connection, with digest auth and CSeq bookkeeping."""

    def __init__(self, url: str, username: str | None, password: str | None,
                 timeout: float):
        self.url = url
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout
        self.cseq = 0
        self.challenge: dict = {}
        self.session_id: str | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        parsed = urlparse(self.url)
        host, port = parsed.hostname, parsed.port or 554
        if not host:
            raise TransportError(f"no host in stream url: {self.url!r}")
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=self.timeout
        )

    async def close(self) -> None:
        if self.writer is None:
            return
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass
        self.reader = self.writer = None

    def _headers(self, method: str, uri: str) -> list[str]:
        self.cseq += 1
        lines = [
            f"{method} {uri} RTSP/1.0",
            f"CSeq: {self.cseq}",
            f"Require: {ONVIF_BACKCHANNEL}",
            "User-Agent: Nurby",
        ]
        if self.session_id:
            lines.append(f"Session: {self.session_id}")
        if self.challenge and self.username:
            auth = digest_response(
                username=self.username, password=self.password,
                method=method, uri=uri, challenge=self.challenge, nc=self.cseq,
            )
            if auth:
                lines.append(f"Authorization: {auth}")
        return lines

    async def request(self, method: str, uri: str,
                      extra: list[str] | None = None) -> tuple[int | None, str, str]:
        """Send one request, retrying once if the camera challenges us.

        The retry is not optional in practice: most cameras answer the
        first request of a session with 401 and a nonce, and a driver
        that treats that as failure works only against unauthenticated
        cameras.
        """
        for attempt in (1, 2):
            lines = self._headers(method, uri) + (extra or [])
            payload = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
            self.writer.write(payload)
            await self.writer.drain()

            raw = await asyncio.wait_for(
                self.reader.read(65536), timeout=self.timeout
            )
            head, body = split_response(raw.decode("utf-8", "replace"))
            status = rtsp_status(head)

            if status == 401 and attempt == 1 and self.username:
                for line in head.splitlines():
                    if line.lower().startswith("www-authenticate"):
                        self.challenge = parse_challenge(line.split(":", 1)[1])
                        break
                if self.challenge:
                    continue
            return status, head, body
        return status, head, body


def _session_id(head: str) -> str | None:
    """The Session header value, without its timeout parameter. Pure."""
    for line in head.splitlines():
        if line.lower().startswith("session:"):
            return line.split(":", 1)[1].strip().split(";")[0].strip()
    return None


def absolute_control(base_url: str, control: str | None) -> str:
    """Resolve a media section's control URL. Pure, for tests.

    SDP control attributes come in three shapes and all three appear in
    the wild: an absolute rtsp:// URL, a relative ``trackID=3``, or ``*``
    meaning the presentation URL itself.
    """
    if not control or control == "*":
        return base_url
    if control.lower().startswith("rtsp://"):
        return control
    separator = "" if base_url.endswith("/") else "/"
    return f"{base_url}{separator}{control}"


class OnvifBackchannelTransport:
    kind = "onvif_backchannel"
    name = "ONVIF audio backchannel"

    async def speak(self, camera, payload: bytes, *, codec: str,
                    sample_rate: int, volume: int = 70,
                    timeout: float = DEFAULT_TIMEOUT) -> None:
        from shared.camera_secrets import unseal

        url = getattr(camera, "stream_url", None) or ""
        if not url.lower().startswith("rtsp"):
            raise TransportUnsupported("camera is not an RTSP source")

        try:
            password = unseal(getattr(camera, "password", None))
        except Exception:
            password = None

        session = _Session(url, getattr(camera, "username", None), password, timeout)
        await session.connect()
        try:
            status, head, body = await session.request(
                "DESCRIBE", url, ["Accept: application/sdp"]
            )
            if status == 401:
                raise TransportError("camera rejected our credentials")
            if status != 200:
                raise TransportError(f"DESCRIBE returned {status}")

            channel = parse_backchannel_sdp(body)
            if channel is None:
                raise TransportUnsupported(
                    "camera advertises no audio backchannel"
                )

            # Speak in whatever the camera offered, not what we assumed.
            # A camera offering only A-law would otherwise be sent mu-law
            # and play noise.
            negotiated = channel.get("codec") or codec
            rate = channel.get("sample_rate") or sample_rate
            if negotiated != codec:
                raise TransportError(
                    f"camera wants {negotiated}, audio was encoded as {codec}"
                )

            control = absolute_control(url, channel.get("control"))
            status, head, _ = await session.request(
                "SETUP", control,
                [f"Transport: RTP/AVP/TCP;unicast;interleaved={RTP_CHANNEL}-{RTCP_CHANNEL}"],
            )
            if status != 200:
                raise TransportError(f"SETUP returned {status}")
            session.session_id = _session_id(head)

            status, _, _ = await session.request("RECORD", url, ["Range: npt=0.000-"])
            if status != 200:
                raise TransportError(f"RECORD returned {status}")

            await self._stream(session, payload, negotiated, rate)
        finally:
            try:
                if session.session_id:
                    await session.request("TEARDOWN", url)
            except Exception:
                logger.debug("TEARDOWN failed", exc_info=True)
            await session.close()

    async def _stream(self, session: _Session, payload: bytes,
                      codec: str, sample_rate: int) -> None:
        """Write RTP packets paced at real time.

        Paced against a monotonic deadline rather than by sleeping a
        fixed interval per packet, so the small cost of each write does
        not accumulate into drift over a long utterance.
        """
        packets = rtp.packetize(payload, codec, sample_rate)
        if not packets:
            return
        interval = rtp.PACKET_MS / 1000.0
        started = time.monotonic()

        for index, packet in enumerate(packets):
            session.writer.write(rtp.interleave(packet, RTP_CHANNEL))
            await session.writer.drain()
            target = started + (index + 1) * interval
            delay = target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
