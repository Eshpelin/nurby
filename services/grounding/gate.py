"""Global GPU admission gate for grounding.

The grounding model is **one shared resource across the whole system**, not
one lane per camera (design §5). So a single global gate serializes access,
with two priority lanes:

- **interactive** (a human is staring at a search spinner) preempts
- **background** (a rule-driven grounding call) at admission time.

Preemption is best-effort and only at *acquire* time: an in-flight GPU
inference cannot be cancelled, so a background call already holding a slot
runs to completion. But whenever an interactive caller is waiting, no new
background caller will be admitted ahead of it.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class PriorityGate:
    """A bounded-concurrency gate where interactive waiters win admission.

    ``concurrency`` is the number of simultaneous inferences allowed (1 on a
    typical single card). Use via the async context manager::

        async with gate.slot(interactive=True):
            ... # call the model
    """

    def __init__(self, concurrency: int = 1):
        if concurrency < 1:
            concurrency = 1
        self._cond = asyncio.Condition()
        self._free = concurrency
        self._interactive_waiting = 0

    @asynccontextmanager
    async def slot(self, *, interactive: bool):
        await self._acquire(interactive)
        try:
            yield
        finally:
            await self._release()

    async def _acquire(self, interactive: bool) -> None:
        async with self._cond:
            if interactive:
                # Announce intent up front. A background waiter's predicate
                # below requires interactive_waiting == 0, so any queued
                # interactive caller blocks new background admissions even
                # when a slot is free. The decrement is in `finally` so a
                # cancelled interactive waiter never wedges the background lane.
                self._interactive_waiting += 1
                try:
                    await self._cond.wait_for(lambda: self._free > 0)
                finally:
                    self._interactive_waiting -= 1
            else:
                await self._cond.wait_for(
                    lambda: self._free > 0 and self._interactive_waiting == 0
                )
            self._free -= 1

    async def _release(self) -> None:
        async with self._cond:
            self._free += 1
            self._cond.notify_all()

    @property
    def interactive_waiting(self) -> int:
        return self._interactive_waiting


# Process-global gate. Sized from config at first import; the API/perception
# workers each get their own (they are separate processes calling the same
# single grounding service, which is itself the real serialization point, so
# this in-process gate just keeps any one worker from spamming the service).
_gate: PriorityGate | None = None


def get_gate() -> PriorityGate:
    global _gate
    if _gate is None:
        from shared.config import settings

        _gate = PriorityGate(concurrency=settings.grounding_max_concurrency)
    return _gate
