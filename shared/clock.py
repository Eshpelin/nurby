"""
Single source of wall-clock truth for the ingestion + perception pipeline.

## Invariant (reviewer-blocker)

Every time-stamped event that crosses the video/audio boundary must use
`stamp_now()` as its authoritative timestamp. Specifically.

- Video frames stamp `capture_t` at the moment ffmpeg demuxes the packet.
- Audio PCM chunks stamp `capture_t` at the same demux boundary.
- STT word offsets are added to the segment's `capture_t` to yield absolute
  times.

Never trust camera PTS. Never trust RTP timestamps. Never trust the wall
clock at the moment a provider returns a result. Cameras commonly have
wrong NTP. Providers have variable latency. Host wall-clock at demux is
the only signal both tracks share.

Violating this invariant breaks the range-overlap join between
`observations` and `transcripts`, silently. No error, just drifted
attribution.

If you need monotonic time for measuring elapsed durations (latency,
cooldowns), use `time.monotonic()` directly. This module is only for
wall-clock stamps that land in the database.
"""

from __future__ import annotations

from datetime import datetime, timezone


def stamp_now() -> datetime:
    """Authoritative wall-clock at the caller's moment.

    Always UTC, always timezone-aware. Do not strip tzinfo before writing
    to the DB. Postgres `TIMESTAMPTZ` columns depend on it.
    """
    return datetime.now(timezone.utc)


def stamp_ms(dt: datetime) -> int:
    """Unix millis for a stamp. Useful for in-memory keys and metrics."""
    return int(dt.timestamp() * 1000)
