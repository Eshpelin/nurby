"""Shared helpers for rule engine pytests.

The engine is exercised without a real database by prefilling
``RuleEngine._rules`` and bumping ``_last_load`` past now so the
``_maybe_reload_rules`` short-circuits. ``_store_event`` and
``execute_action`` are monkeypatched on a per-test basis so tests do
not need Postgres, Redis, or any provider.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock


class FakeRedis:
    """Minimal in-memory async stand-in for ``redis.asyncio.Redis``.

    Implements just enough surface for the cooldown engine. ``get``,
    ``set`` (with ``ex`` TTL), ``expire``, and ``aclose``. TTLs are
    enforced lazily on read so tests can fast-forward time by mutating
    the internal ``_expires`` map directly if needed. The class also
    accepts an optional ``fail_mode`` so a test can simulate Redis
    outages without restarting anything.
    """

    def __init__(self, fail_mode: str | None = None):
        self._data: dict[str, str] = {}
        self._expires: dict[str, float] = {}
        # fail_mode in {None, "get", "set", "all"}
        self.fail_mode = fail_mode

    async def get(self, key: str):
        if self.fail_mode in ("get", "all"):
            raise RuntimeError("simulated redis GET failure")
        exp = self._expires.get(key)
        if exp is not None and exp <= time.time():
            self._data.pop(key, None)
            self._expires.pop(key, None)
            return None
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        if self.fail_mode in ("set", "all"):
            raise RuntimeError("simulated redis SET failure")
        self._data[key] = str(value)
        if ex is not None:
            self._expires[key] = time.time() + ex
        return True

    async def expire(self, key: str, seconds: int):
        if key in self._data:
            self._expires[key] = time.time() + seconds
            return True
        return False

    async def aclose(self):
        return None

    def ttl_for(self, key: str) -> float | None:
        """Test helper. seconds remaining until expiry, or None."""
        exp = self._expires.get(key)
        if exp is None:
            return None
        return exp - time.time()


@dataclass
class FakeRule:
    name: str
    trigger_pattern: dict
    actions: list | dict = field(default_factory=lambda: [{"type": "broadcast"}])
    conditions: dict | None = None
    cooldown_seconds: int = 0
    enabled: bool = True
    severity: str = "alert"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    snoozed_until: object = None


def install_engine(monkeypatch, rules, *, redis=None, share_redis=None):
    """Build a RuleEngine, prefill rules, and stub out IO.

    Returns (engine, recorder) where recorder is an ``AsyncMock`` that
    captures every ``execute_action`` invocation as positional args.

    ``redis`` lets tests inject a ``FakeRedis`` to exercise the
    cross-process cooldown path without touching a real broker. Pass
    ``share_redis`` for the second engine in a "two-worker" scenario so
    both engines hit the same in-memory store. Pass ``redis=False`` to
    explicitly disable Redis and force the degraded microcache-only
    code path.
    """
    from services.events import engine as engine_mod

    eng = engine_mod.RuleEngine()
    eng._rules = list(rules)
    # Set far in the future so _maybe_reload_rules never refreshes.
    eng._last_load = time.monotonic() + 10_000
    # Pin the cooldown backend cache so the engine never hits the
    # database trying to read the app setting.
    eng._cooldown_backend = "redis"
    eng._cooldown_backend_loaded_at = time.monotonic() + 10_000

    if share_redis is not None:
        eng._cooldown_redis = share_redis
    elif redis is False:
        # Force degraded mode. No Redis available at all.
        eng._cooldown_redis_failed = True
    elif redis is not None:
        eng._cooldown_redis = redis
    else:
        eng._cooldown_redis = FakeRedis()

    recorder = AsyncMock()

    async def _store_event(*args, **kwargs):
        return uuid.uuid4()

    # The fire path runs through services.events.firing now: it resolves
    # execute_action from services.events.actions at call time and persists via
    # firing.store_event. Patch both seams so tests need no DB and can capture
    # every action dispatch via the returned recorder.
    from services.events import actions as actions_mod
    from services.events import firing as firing_mod

    monkeypatch.setattr(actions_mod, "execute_action", recorder)
    monkeypatch.setattr(firing_mod, "store_event", _store_event)
    return eng, recorder
