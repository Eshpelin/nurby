"""Router-level controls. STT budget, worker sizing, transcribe timeout."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services.perception.audio import router as router_mod
from services.perception.audio.router import (
    CameraAudioRouter,
    _resolve_worker_count,
)
from services.perception.audio.types import SpeechSegment, TranscriptResult


def _seg(ms: int = 2000) -> SpeechSegment:
    t0 = datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc)
    return SpeechSegment(
        camera_id=uuid.uuid4(),
        started_at=t0,
        ended_at=t0 + timedelta(milliseconds=ms),
        pcm=b"\x00" * (ms * 32),
        sample_rate=16000,
        duration_ms=ms,
    )


class _FakeRedis:
    def __init__(self, start: float = 0.0):
        self.store: dict[str, float] = {}
        self._start = start

    async def get(self, k):
        return self.store.get(k, self._start)

    async def incrbyfloat(self, k, v):
        self.store[k] = self.store.get(k, 0.0) + v
        return self.store[k]

    async def expire(self, k, ttl):
        return True


def _router(budget: int) -> CameraAudioRouter:
    return CameraAudioRouter(
        camera_id=uuid.uuid4(),
        stream_url="x",
        provider_kind="mock",
        provider_kwargs={},
        write_callback=lambda *a, **k: None,
        budget_minutes_per_hour=budget,
    )


# ---- worker sizing -------------------------------------------------------

class _P:
    def __init__(self, is_local):
        self.is_local = is_local


def test_worker_count_cloud_uses_cloud_constant():
    assert _resolve_worker_count(_P(False)) == router_mod.AUDIO_STT_WORKERS_CLOUD


def test_worker_count_local_clamped_to_cpu_and_positive():
    n = _resolve_worker_count(_P(True))
    assert n >= 1
    assert n <= max(1, router_mod.AUDIO_STT_WORKERS_LOCAL)


# ---- budget gate ---------------------------------------------------------

@pytest.mark.asyncio
async def test_unlimited_budget_always_allows():
    r = _router(0)
    assert await r._within_budget(_seg()) is True


@pytest.mark.asyncio
async def test_budget_allows_when_under_then_blocks_when_over():
    r = _router(1)  # 1 minute = 60 seconds per hour
    fake = _FakeRedis(start=0.0)
    r._redis = fake
    r._get_redis = lambda: _await(fake)  # type: ignore

    seg = _seg(ms=2000)  # 2 seconds
    assert await r._within_budget(seg) is True
    await r._record_usage(seg)
    # Simulate having transcribed 59s already.
    key = r._usage_key()
    fake.store[key] = 61.0
    assert await r._within_budget(seg) is False


@pytest.mark.asyncio
async def test_budget_read_failure_fails_open():
    r = _router(1)

    class _Boom:
        async def get(self, k):
            raise RuntimeError("redis down")

    r._redis = _Boom()
    r._get_redis = lambda: _await(r._redis)  # type: ignore
    assert await r._within_budget(_seg()) is True


# ---- transcribe timeout --------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_times_out_and_does_not_write(monkeypatch):
    monkeypatch.setattr(router_mod, "AUDIO_STT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(router_mod, "AUDIO_STT_RETRIES", 1)

    wrote = {"n": 0}

    async def write(*a, **k):
        wrote["n"] += 1

    class _SlowProvider:
        kind = "slow"
        is_local = True

        async def transcribe(self, seg):
            await asyncio.sleep(1.0)  # >> timeout
            return TranscriptResult(text="never", provider="slow", model="x")

    r = CameraAudioRouter(
        camera_id=uuid.uuid4(),
        stream_url="x",
        provider_kind="slow",
        provider_kwargs={},
        write_callback=write,
        budget_minutes_per_hour=0,
    )
    r._provider = _SlowProvider()

    await asyncio.wait_for(r._dispatch(_seg()), timeout=2.0)
    assert wrote["n"] == 0
    # Retries exhausted on timeout -> cooldown armed.
    import time as _t
    assert r._cooldown_until > _t.monotonic()


async def _await(v):
    return v
