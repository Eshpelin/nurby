"""Find out whether a camera can be made to speak (issue #153).

Getting audio *into* a camera is the whole risk of the voice feature, and
it is hardware-dependent in a way no design resolves. This module answers
the question empirically, per camera, and records what it saw.

Three things are attempted, cheapest and most standard first:

1. **ONVIF backchannel.** An RTSP ``DESCRIBE`` carrying
   ``Require: www.onvif.org/ver20/backchannel``. A camera that supports
   it answers with an extra audio media section marked ``a=sendonly``,
   which is the channel we push into. This is the only vendor-neutral
   answer. See :func:`parse_backchannel_sdp` for why that direction reads
   backwards.
2. **Vendor HTTP.** Hikvision ISAPI, Dahua CGI, Reolink and friends each
   expose their own two-way audio endpoint. Narrower, but often the only
   thing that works.
3. **Nothing.** Recorded as a finding rather than left blank. A camera
   with no speaker is a fact the UI needs to state plainly, and an
   external speaker through the existing ``Device`` row is the answer
   for those.

The parsing is pure and the IO is thin, so the interesting half is
testable against recorded responses instead of against hardware nobody
has in CI.

**Unverified against hardware.** The backchannel handling here follows
the ONVIF streaming spec and is tested against recorded SDP, but no
camera in this environment was reachable when it was written. The
sendonly-vs-recvonly reading is the single highest-risk assumption in the
voice work and should be confirmed on a real device before #155 builds a
transport on top of it.

**Tapo note.** TP-Link Tapo cameras do two-way audio over a proprietary
authenticated HTTPS API rather than the ONVIF backchannel, even though
they speak ONVIF for video. They are detected here so the probe reports
something honest, but supporting them is its own piece of work.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger("nurby.voice.probe")

ONVIF_BACKCHANNEL = "www.onvif.org/ver20/backchannel"

# How long to wait on a camera that may simply not be there. Short: a
# probe sweep runs over every camera in the house and one unplugged unit
# should not hold it up.
DEFAULT_TIMEOUT = 4.0

# RTP payload names we can actually produce, in the order we would rather
# have them. G.711 both ways is what services/voice/audio.py emits.
PREFERRED_CODECS = ("pcmu", "pcma", "l16")

TRANSPORT_NONE = "none"
TRANSPORT_ONVIF = "onvif_backchannel"

# Vendor fingerprints, matched against an ONVIF manufacturer string or a
# stream URL. Deliberately loose: this only picks which endpoint to try
# next, and a wrong guess costs one failed request.
_VENDOR_HINTS = (
    ("hikvision", re.compile(r"hikvision|hik-?connect|/Streaming/Channels", re.I)),
    ("dahua", re.compile(r"dahua|amcrest|/cam/realmonitor", re.I)),
    ("reolink", re.compile(r"reolink|/h264Preview", re.I)),
    ("tapo", re.compile(r"tapo|tp-?link|/stream1|/stream2", re.I)),
    ("axis", re.compile(r"axis|/axis-media", re.I)),
)

# Where each vendor exposes two-way audio, for the probe to try. Paths
# only; the probe checks reachability rather than pushing audio.
VENDOR_ENDPOINTS = {
    "hikvision": "/ISAPI/System/TwoWayAudio/channels",
    "dahua": "/cgi-bin/audio.cgi?action=getCaps",
    "reolink": "/api.cgi?cmd=GetAbility",
    "axis": "/axis-cgi/param.cgi?action=list&group=AudioSource",
}


@dataclass
class ProbeResult:
    """What one camera turned out to support."""

    transport: str = TRANSPORT_NONE
    supported: bool = False
    codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    endpoint: str | None = None
    vendor: str | None = None
    error: str | None = None
    detail: dict = field(default_factory=dict)


# ---- pure parsing --------------------------------------------------------


def infer_vendor(*hints: str | None) -> str | None:
    """Guess the vendor from any strings we happen to have. Pure."""
    haystack = " ".join(h for h in hints if h)
    if not haystack.strip():
        return None
    for vendor, pattern in _VENDOR_HINTS:
        if pattern.search(haystack):
            return vendor
    return None


def rtsp_status(response: str) -> int | None:
    """Status code from an RTSP response head. Pure, for tests."""
    if not response:
        return None
    match = re.match(r"RTSP/\d\.\d\s+(\d{3})", response.strip())
    return int(match.group(1)) if match else None


def parse_backchannel_sdp(sdp: str) -> dict | None:
    """The audio channel a camera offers us to push into. Pure, for tests.

    Returns ``{"codec", "sample_rate", "channels", "control"}`` or None.

    The distinguishing mark is an audio media section carrying
    ``a=sendonly``, and the direction is the trap in this whole module.

    In an RTSP server's SDP the attributes are written from the CLIENT's
    point of view. Media the server streams down to us are marked
    ``a=recvonly`` (we receive); the ONVIF backchannel, which we push up
    to the camera, is marked ``a=sendonly`` (we send). So the camera's
    microphone feed is recvonly and the speaker channel is sendonly,
    which reads backwards if you assume the server is describing itself.

    Picking the wrong one would select the microphone stream and push
    audio at a track that will never play it, failing silently in the
    most confusing possible way, so only ``sendonly`` counts here.
    """
    if not sdp:
        return None

    sections: list[list[str]] = []
    current: list[str] | None = None
    for raw in sdp.splitlines():
        line = raw.strip()
        if line.startswith("m="):
            current = [line]
            sections.append(current)
        elif current is not None:
            current.append(line)

    for section in sections:
        media = section[0]
        if not media.startswith("m=audio"):
            continue
        body = "\n".join(section)
        # Only a section WE send on is a backchannel. See the docstring:
        # SDP directions here are from the client's point of view.
        if not re.search(r"^a=sendonly\s*$", body, re.M):
            continue

        payloads = media.split()[3:]
        codec = sample_rate = channels = None
        for payload in payloads:
            rtpmap = re.search(
                rf"^a=rtpmap:{re.escape(payload)}\s+([A-Za-z0-9-]+)/(\d+)(?:/(\d+))?",
                body, re.M,
            )
            if not rtpmap:
                continue
            name = rtpmap.group(1).lower()
            if name in PREFERRED_CODECS or codec is None:
                codec = name
                sample_rate = int(rtpmap.group(2))
                channels = int(rtpmap.group(3) or 1)
            if name in PREFERRED_CODECS:
                break

        control = None
        control_match = re.search(r"^a=control:(\S+)", body, re.M)
        if control_match:
            control = control_match.group(1)

        return {
            "codec": codec,
            "sample_rate": sample_rate,
            "channels": channels,
            "control": control,
        }
    return None


def usable_codec(codec: str | None) -> bool:
    """Whether we can actually produce this payload. Pure.

    A camera offering only AAC on its backchannel is a camera we cannot
    speak through today, and saying so is more useful than recording it
    as supported and failing at rule-fire time.
    """
    return (codec or "").lower() in PREFERRED_CODECS


def build_describe(url: str, cseq: int = 1, auth: str | None = None) -> str:
    """An RTSP DESCRIBE asking for the backchannel. Pure, for tests."""
    lines = [
        f"DESCRIBE {url} RTSP/1.0",
        f"CSeq: {cseq}",
        "Accept: application/sdp",
        f"Require: {ONVIF_BACKCHANNEL}",
        "User-Agent: Nurby",
    ]
    if auth:
        lines.append(f"Authorization: {auth}")
    return "\r\n".join(lines) + "\r\n\r\n"


def split_response(raw: str) -> tuple[str, str]:
    """Split an RTSP response into head and body. Pure, for tests."""
    for separator in ("\r\n\r\n", "\n\n"):
        if separator in raw:
            head, body = raw.split(separator, 1)
            return head, body
    return raw, ""


# ---- IO ------------------------------------------------------------------


async def rtsp_describe(
    stream_url: str, username: str | None = None, password: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int | None, str, str]:
    """Send one DESCRIBE and return ``(status, head, body)``.

    A minimal client on purpose. The full RTSP session (SETUP, RECORD,
    interleaved RTP) belongs to the transport in #155; all this needs to
    know is whether the camera advertises a backchannel at all.
    """
    parsed = urlparse(stream_url)
    host = parsed.hostname
    port = parsed.port or 554
    if not host:
        raise ValueError(f"no host in stream url: {stream_url!r}")

    reader = writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        auth = None
        if username:
            import base64

            token = base64.b64encode(
                f"{username}:{password or ''}".encode("utf-8")
            ).decode("ascii")
            auth = f"Basic {token}"

        writer.write(build_describe(stream_url, 1, auth).encode("utf-8"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(65536), timeout=timeout)
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    text = raw.decode("utf-8", "replace")
    head, body = split_response(text)
    return rtsp_status(head), head, body


async def probe_camera(camera, timeout: float = DEFAULT_TIMEOUT) -> ProbeResult:
    """Work out how, if at all, this camera can be spoken through.

    Never raises. An unreachable camera is a finding ("we looked, it did
    not answer"), and a sweep over a house must not stop at the one unit
    that is unplugged.
    """
    from shared.camera_secrets import unseal

    stream_url = getattr(camera, "stream_url", None) or ""
    vendor = infer_vendor(stream_url, getattr(camera, "name", None))
    result = ProbeResult(vendor=vendor)

    if not stream_url.lower().startswith("rtsp"):
        result.error = f"not an RTSP camera (stream_type={getattr(camera, 'stream_type', None)!r})"
        result.detail = {"stream_url_scheme": urlparse(stream_url).scheme}
        return result

    try:
        password = unseal(getattr(camera, "password", None))
    except Exception:
        password = None

    try:
        status, head, body = await rtsp_describe(
            stream_url, getattr(camera, "username", None), password, timeout,
        )
    except (asyncio.TimeoutError, OSError, ValueError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.detail = {"stage": "rtsp_describe"}
        return result

    result.detail = {
        "rtsp_status": status,
        "head": head[:500],
        "sdp": body[:2000],
    }

    if status == 401:
        result.error = "camera required authentication we could not satisfy"
        return result
    if status != 200:
        result.error = f"DESCRIBE returned {status}"
        return result

    channel = parse_backchannel_sdp(body)
    if channel is None:
        result.error = "camera answered but advertised no backchannel"
        if vendor in VENDOR_ENDPOINTS:
            result.detail["try_next"] = VENDOR_ENDPOINTS[vendor]
        elif vendor == "tapo":
            result.detail["try_next"] = (
                "Tapo two-way audio uses a proprietary authenticated HTTPS "
                "API, not the ONVIF backchannel"
            )
        return result

    result.transport = TRANSPORT_ONVIF
    result.codec = channel["codec"]
    result.sample_rate = channel["sample_rate"]
    result.channels = channel["channels"]
    result.endpoint = channel["control"]
    result.supported = usable_codec(channel["codec"])
    if not result.supported:
        result.error = (
            f"backchannel offers {channel['codec']!r}, which we cannot produce"
        )
    return result


async def store_result(db, camera_id, result: ProbeResult):
    """Upsert the probe result. One row per camera, latest wins."""
    from sqlalchemy import select

    from shared.models import SpeakerCapability

    row = (
        await db.execute(
            select(SpeakerCapability).where(SpeakerCapability.camera_id == camera_id)
        )
    ).scalars().first()
    if row is None:
        row = SpeakerCapability(camera_id=camera_id)
        db.add(row)

    row.transport = result.transport
    row.supported = result.supported
    row.codec = result.codec
    row.sample_rate = result.sample_rate
    row.channels = result.channels
    row.endpoint = result.endpoint
    row.vendor = result.vendor
    row.probe_error = result.error
    row.detail = result.detail
    return row
