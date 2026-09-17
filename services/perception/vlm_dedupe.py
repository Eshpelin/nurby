"""
Perceptual-hash dedupe for VLM enqueue.

Scenes that haven't visibly changed (parked car, sleeping person, slow
panning across an empty room) get the same VLM caption every time we
call. That's pure waste on a slow Ollama host where each frame costs
~15 seconds.

This module computes a cheap 64-bit DCT-based perceptual hash (pHash)
of each candidate frame. Before enqueue, we compare against a small
window of recently accepted hashes for the same camera; if Hamming
distance to any of them is below a tunable threshold we skip the
enqueue entirely. The ring is stored under a Redis key with a short
TTL so an idle camera naturally forgets its recent scenes if it stops
publishing keyframes.

Why a window and not just the last hash (issue #223): oscillating
scenes — A/B/A/B, e.g. a flag flapping across a doorway, a wiper
sweeping a windshield — flip between two hashes. Compared only against
the last accepted hash, every flip looks "novel" and we caption the
same scene on every swing. With a ring, both A and B stay in the
comparison set after the first cycle and the oscillation is bounded.

pHash basics.
  1. Resize to 32x32 grayscale.
  2. 2D DCT over the 32x32 matrix.
  3. Take the top-left 8x8 low-frequency block.
  4. Mean of the 63 values excluding the DC term [0,0].
  5. Bit i = 1 if dct[i] > mean else 0, packed into a 64-bit int.

Independent of brightness shifts. Stable under small JPEG compression
artifacts. Sensitive to actual scene change.
"""

from __future__ import annotations

import json
import logging

import cv2
import numpy as np

logger = logging.getLogger("nurby.perception.vlm_dedupe")


# Hamming distance threshold under which two hashes are "the same scene."
# 64-bit hash; 0 = identical, 64 = inverted. Empirically <=8 catches near-
# duplicates without false-merging similar-but-different scenes.
DEFAULT_HASH_THRESHOLD = 8

# Redis key for the recent-hash ring per camera. TTL bounds how long an
# idle camera "remembers" its recent scenes before fresh frames are forced
# through. Default 5 minutes so a camera that goes idle and then becomes
# active again does at least one VLM call to confirm change.
LAST_HASH_KEY = "nurby:vlm_last_phash"
LAST_HASH_TTL_SECONDS = 300

# How many recently accepted hashes each camera compares against. Large
# enough to hold both sides of an oscillating scene a few times over,
# small enough that distinct-scene memory stays bounded (issue #223).
HASH_WINDOW_SIZE = 12


def phash(frame: np.ndarray) -> int:
    """64-bit DCT perceptual hash. Pure numpy + OpenCV, no extras."""
    if frame is None or frame.size == 0:
        return 0
    # 1. grayscale + resize to 32x32. cv2.resize default INTER_LINEAR.
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    # 2. 2D DCT.
    dct = cv2.dct(small)
    # 3. low-freq 8x8 block.
    block = dct[:8, :8]
    # 4. mean over 63 values excluding DC [0,0].
    flat = block.flatten()
    mean = (flat.sum() - flat[0]) / 63.0
    # 5. pack bits MSB-first into a 64-bit int.
    bits = (flat > mean).astype(np.uint8)
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two 64-bit hashes."""
    return bin(a ^ b).count("1")


def _parse_ring(raw) -> list[int]:
    """Parse a stored hash ring. Accepts the current JSON-list form and
    the legacy single-int string written before the window existed, so a
    rolling deployment never chokes on old values."""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(parsed, int):
        return [parsed]
    if isinstance(parsed, list):
        out: list[int] = []
        for h in parsed:
            try:
                out.append(int(h))
            except (ValueError, TypeError):
                continue
        return out
    return []


async def should_enqueue(
    redis,
    camera_id: str,
    frame: np.ndarray,
    *,
    threshold: int = DEFAULT_HASH_THRESHOLD,
    ttl: int = LAST_HASH_TTL_SECONDS,
    window: int = HASH_WINDOW_SIZE,
) -> tuple[bool, int, int | None]:
    """Return (allow, this_hash, prior_hash_or_none).

    Computes the pHash for `frame`, compares to the recent-hash ring for
    `camera_id` from Redis, and decides whether the frame is novel enough
    to forward to the VLM. On allow, the ring is extended with this
    frame's hash (trimmed to `window` entries) and stored with `ttl`.

    `prior_hash` is the matched ring entry when blocking (the nearest
    scene), otherwise the most recent prior hash, or None when the camera
    had none.

    The caller is responsible for actually enqueuing on allow=True and
    skipping otherwise. We never mutate state when allow=False so the
    known-hash ring continues to ratchet only on accepted frames.
    """
    this_hash = phash(frame)
    key = f"{LAST_HASH_KEY}:{camera_id}"
    prior_raw = None
    try:
        prior_raw = await redis.get(key)
    except Exception:
        logger.exception("dedupe Redis GET failed camera=%s; allowing", camera_id)
        return True, this_hash, None

    prior_hashes = _parse_ring(prior_raw) if prior_raw is not None else []

    nearest: tuple[int, int] | None = None
    for prior in prior_hashes:
        d = hamming_distance(this_hash, prior)
        if d <= threshold and (nearest is None or d < nearest[0]):
            nearest = (d, prior)
    if nearest is not None:
        return False, this_hash, nearest[1]

    keep = prior_hashes[-(window - 1):] if window > 1 else []
    try:
        await redis.setex(key, ttl, json.dumps(keep + [this_hash]))
    except Exception:
        logger.debug("dedupe Redis SETEX failed camera=%s", camera_id, exc_info=True)
    return True, this_hash, (prior_hashes[-1] if prior_hashes else None)


__all__ = [
    "phash",
    "hamming_distance",
    "should_enqueue",
    "DEFAULT_HASH_THRESHOLD",
    "LAST_HASH_KEY",
    "LAST_HASH_TTL_SECONDS",
    "HASH_WINDOW_SIZE",
]
