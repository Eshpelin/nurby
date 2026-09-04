"""RTP packetisation for the audio we push into a camera (#155).

The ONVIF backchannel wants RTP, not a raw byte stream: a camera decoding
G.711 needs packet boundaries, a sequence number to detect loss, and a
timestamp to pace playback. Sending the payload as one large blob mostly
produces silence or a burst of noise, depending on the vendor.

Small enough to implement directly (RFC 3550's fixed header is twelve
bytes and we never need CSRCs, padding, or extensions) and worth having
as pure functions so packet layout is testable without a camera.
"""

from __future__ import annotations

import random
import struct

# 20 ms is the universal default for telephony audio, and at 8 kHz G.711
# that is exactly 160 bytes of payload. Cameras are built around this
# number; larger packets are often dropped outright.
PACKET_MS = 20

RTP_VERSION = 2

# Static payload types from RFC 3551. These are fixed numbers, not
# negotiated, which is why G.711 works without SDP agreement in practice.
PAYLOAD_TYPES = {
    "pcmu": 0,
    "pcma": 8,
    "l16": 11,
}


def payload_type(codec: str) -> int:
    """RTP payload type for a codec name. Pure, for tests."""
    try:
        return PAYLOAD_TYPES[(codec or "").lower()]
    except KeyError:
        raise ValueError(f"no static RTP payload type for codec {codec!r}") from None


def frame_size(codec: str, sample_rate: int, packet_ms: int = PACKET_MS) -> int:
    """Payload bytes per packet. Pure, for tests."""
    samples = int(sample_rate * packet_ms / 1000)
    # L16 is two bytes per sample; the G.711 variants are one.
    return samples * (2 if (codec or "").lower() == "l16" else 1)


def build_packet(
    payload: bytes, *, sequence: int, timestamp: int, ssrc: int,
    pt: int, marker: bool = False,
) -> bytes:
    """One RTP packet. Pure, for tests.

    Sequence and timestamp wrap at 16 and 32 bits respectively, which
    matters for anything speaking longer than about six hours but is
    handled here so the caller never has to think about it.
    """
    first = (RTP_VERSION << 6)
    second = (0x80 if marker else 0x00) | (pt & 0x7F)
    header = struct.pack(
        "!BBHII", first, second, sequence & 0xFFFF, timestamp & 0xFFFFFFFF, ssrc
    )
    return header + payload


def packetize(
    payload: bytes, codec: str, sample_rate: int, *,
    ssrc: int | None = None, packet_ms: int = PACKET_MS,
) -> list[bytes]:
    """Split encoded audio into RTP packets. Pure apart from the SSRC draw.

    The first packet carries the marker bit, which is how a receiver
    knows a talkspurt has started rather than that it joined mid-stream.
    """
    if not payload:
        return []

    pt = payload_type(codec)
    size = frame_size(codec, sample_rate, packet_ms)
    if size <= 0:
        raise ValueError("frame size must be positive")

    ssrc = ssrc if ssrc is not None else random.getrandbits(32)
    sequence = random.getrandbits(16)
    timestamp = random.getrandbits(32)
    # Timestamp advances in SAMPLES, not bytes or packets. For L16 that
    # is half the byte count, which is the kind of detail that produces
    # audio at double speed when it is got wrong.
    step = int(sample_rate * packet_ms / 1000)

    packets = []
    for index, offset in enumerate(range(0, len(payload), size)):
        chunk = payload[offset:offset + size]
        packets.append(build_packet(
            chunk,
            sequence=sequence + index,
            timestamp=timestamp + index * step,
            ssrc=ssrc,
            pt=pt,
            marker=(index == 0),
        ))
    return packets


def interleave(packet: bytes, channel: int = 0) -> bytes:
    """Wrap a packet for RTSP's interleaved TCP framing. Pure, for tests.

    ``$`` then the channel then a 16-bit length, per RFC 2326 section 10.12.
    Sending over the existing TCP control connection avoids a second
    socket and, more usefully, avoids every NAT problem UDP would bring
    on a household network.
    """
    return b"$" + bytes([channel & 0xFF]) + struct.pack("!H", len(packet)) + packet


def parse_header(packet: bytes) -> dict:
    """Read back an RTP header. Pure, for tests and for inspecting a
    capture."""
    if len(packet) < 12:
        raise ValueError("packet is shorter than an RTP header")
    first, second, sequence, timestamp, ssrc = struct.unpack("!BBHII", packet[:12])
    return {
        "version": first >> 6,
        "marker": bool(second & 0x80),
        "payload_type": second & 0x7F,
        "sequence": sequence,
        "timestamp": timestamp,
        "ssrc": ssrc,
        "payload": packet[12:],
    }
