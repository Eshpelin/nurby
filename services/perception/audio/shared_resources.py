"""Process-wide cache for heavy, reusable STT provider resources.

A :class:`CameraAudioRouter` builds one provider instance per camera, so
without sharing, ten cameras would load ten copies of the same Whisper
model (hundreds of MB each) or open ten independent HTTP clients. The
heavy part of a provider is almost always camera-independent:

* local backends share the loaded model (the per-camera bit, language, is
  a transcribe-time argument, not part of the model)
* cloud backends share the HTTP client / connection pool / auth session

Both fit the same shape: a keyed singleton created once and reused. This
module is that singleton store. Provider instances stay thin and cheap;
the expensive resource lives here, keyed by whatever makes it reusable
(``(model, device)`` for Whisper, ``(base_url,)`` for a cloud client).

The factory runs at most once per key even under concurrent first use, so
two cameras starting together never double-load.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Hashable, TypeVar

logger = logging.getLogger("nurby.perception.audio.shared")

T = TypeVar("T")

_resources: dict[Hashable, object] = {}
# One lock per key so first-creation of resource A does not block callers
# waiting on the already-built resource B.
_locks: dict[Hashable, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(key: Hashable) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


async def get_or_create(
    key: Hashable, factory: Callable[[], Awaitable[T]]
) -> T:
    """Return the shared resource for ``key``, creating it once on demand.

    ``factory`` is an async callable that builds the resource. It runs at
    most once per key for the lifetime of the process, even if several
    callers race on the first use.
    """
    cached = _resources.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    lock = await _lock_for(key)
    async with lock:
        cached = _resources.get(key)
        if cached is None:
            logger.info("creating shared STT resource %r", key)
            cached = await factory()
            _resources[key] = cached
    return cached  # type: ignore[return-value]


def clear() -> None:
    """Drop all shared resources. Test-only. Does not close clients."""
    _resources.clear()
    _locks.clear()
