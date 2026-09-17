"""pHash dedupe tests."""

import asyncio
import json

import numpy as np

from services.perception.vlm_dedupe import (
    DEFAULT_HASH_THRESHOLD,
    HASH_WINDOW_SIZE,
    hamming_distance,
    phash,
    should_enqueue,
)


def _grad_frame(seed=0):
    """Reproducible non-trivial frame; pure random noise so DCT
    energy spreads across the low-freq block enough for the hash to
    differentiate."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)


def test_phash_identical_distance_zero():
    f = _grad_frame(seed=1)
    a = phash(f)
    b = phash(f.copy())
    assert hamming_distance(a, b) == 0


def test_phash_different_scenes_far_apart():
    a = phash(_grad_frame(seed=1))
    b = phash(_grad_frame(seed=99))
    assert hamming_distance(a, b) > DEFAULT_HASH_THRESHOLD


class _FakeRedis:
    def __init__(self):
        self._kv = {}

    async def get(self, key):
        return self._kv.get(key)

    async def setex(self, key, _ttl, value):
        self._kv[key] = value


def _run(c):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(c)


def test_should_enqueue_first_frame_allows_and_stores():
    r = _FakeRedis()
    frame = _grad_frame(seed=2)
    allow, h, prior = _run(should_enqueue(r, "cam-1", frame))
    assert allow is True
    assert prior is None
    # Stored under expected key as a JSON ring holding this hash.
    stored = _run(r.get("nurby:vlm_last_phash:cam-1"))
    assert stored is not None
    assert json.loads(stored) == [h]


def test_should_enqueue_skips_duplicate():
    r = _FakeRedis()
    frame = _grad_frame(seed=3)
    _run(should_enqueue(r, "cam-2", frame))
    allow, _h, prior = _run(should_enqueue(r, "cam-2", frame.copy()))
    assert allow is False
    assert prior is not None


def test_should_enqueue_allows_when_scene_changes():
    r = _FakeRedis()
    _run(should_enqueue(r, "cam-3", _grad_frame(seed=4)))
    allow, _h, _p = _run(should_enqueue(r, "cam-3", _grad_frame(seed=77)))
    assert allow is True


def test_should_enqueue_allows_on_redis_failure():
    """Redis outage must never starve the VLM pipeline."""

    class _BrokenRedis:
        async def get(self, _k):
            raise RuntimeError("redis down")

        async def setex(self, _k, _t, _v):
            raise RuntimeError("redis down")

    allow, _h, prior = _run(should_enqueue(_BrokenRedis(), "cam-4", _grad_frame(seed=5)))
    assert allow is True
    assert prior is None


# ── issue #223: oscillating scenes vs the hash window ────────────────────


def test_oscillating_scene_blocked_after_first_cycle():
    """A/B/A: the third frame matches A inside the window and is skipped.

    Against a last-hash-only comparison, every A re-appearance differed
    from the last accepted B and burned a VLM call on each flip."""
    r = _FakeRedis()
    a = _grad_frame(seed=11)
    b = _grad_frame(seed=99)
    assert hamming_distance(phash(a), phash(b)) > DEFAULT_HASH_THRESHOLD

    allow1, _h, _p = _run(should_enqueue(r, "cam-osc", a))
    allow2, _h, _p = _run(should_enqueue(r, "cam-osc", b))
    allow3, _h, matched = _run(should_enqueue(r, "cam-osc", a.copy()))

    assert allow1 is True
    assert allow2 is True
    assert allow3 is False
    assert matched == phash(a)


def test_window_does_not_over_suppress_distinct_scenes():
    """More distinct scenes than the window holds → every one allowed.

    Suppression only applies to scenes repeating within the window."""
    r = _FakeRedis()
    allowed = 0
    for seed in range(1, HASH_WINDOW_SIZE + 2):
        allow, _h, _p = _run(should_enqueue(r, "cam-many", _grad_frame(seed=seed * 7)))
        allowed += int(allow)
    assert allowed == HASH_WINDOW_SIZE + 1


def test_ring_trims_to_window_size():
    """After window+1 accepts, the oldest hash is evicted: re-showing the
    original scene is allowed again (bounded memory, bounded suppression)."""
    r = _FakeRedis()
    first = _grad_frame(seed=3)
    _run(should_enqueue(r, "cam-trim", first))
    for seed in range(50, 50 + HASH_WINDOW_SIZE):
        _run(should_enqueue(r, "cam-trim", _grad_frame(seed=seed)))
    allow, _h, prior = _run(should_enqueue(r, "cam-trim", first.copy()))
    assert allow is True
    assert prior is not None
    stored = json.loads(_run(r.get("nurby:vlm_last_phash:cam-trim")))
    assert len(stored) == HASH_WINDOW_SIZE


def test_legacy_single_hash_value_still_parsed():
    """A rolling deployment reads a pre-window single-int value without
    choking: the legacy hash still dedupes its own scene."""
    r = _FakeRedis()
    frame = _grad_frame(seed=8)
    legacy_hash = phash(frame)
    r._kv["nurby:vlm_last_phash:cam-legacy"] = str(legacy_hash)

    allow, _h, matched = _run(should_enqueue(r, "cam-legacy", frame.copy()))
    assert allow is False
    assert matched == legacy_hash
