"""Shared STT resource cache. one creation per key, even under races."""

from __future__ import annotations

import asyncio

import pytest

from services.perception.audio import shared_resources


@pytest.fixture(autouse=True)
def _clear():
    shared_resources.clear()
    yield
    shared_resources.clear()


@pytest.mark.asyncio
async def test_factory_runs_once_per_key():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return object()

    a = await shared_resources.get_or_create("k", factory)
    b = await shared_resources.get_or_create("k", factory)
    assert a is b
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_concurrent_first_use_does_not_double_create():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        await asyncio.sleep(0.01)  # widen the race window
        return object()

    results = await asyncio.gather(
        *[shared_resources.get_or_create("same", factory) for _ in range(10)]
    )
    assert calls["n"] == 1
    assert all(r is results[0] for r in results)


@pytest.mark.asyncio
async def test_distinct_keys_create_distinct_resources():
    async def factory():
        return object()

    a = await shared_resources.get_or_create(("m", "cpu"), factory)
    b = await shared_resources.get_or_create(("m", "cuda"), factory)
    assert a is not b
