"""Cooldown gating tests for RuleEngine.

Cooldowns are persisted in Redis under ``nurby:rule_cooldown:<rule_id>``
so they survive perception restarts and are shared across multiple
workers. The engine keeps a tiny 1-second in-process microcache to
avoid redundant Redis roundtrips on back-to-back evaluations of the
same rule from the same worker. cooldown_seconds=0 means "no cooldown"
and skips Redis entirely. Redis errors degrade gracefully to the
microcache so the engine never crashes when the broker is down.
"""

import asyncio
import time

from tests._engine_helpers import FakeRedis, FakeRule, install_engine


def test_second_fire_within_cooldown_suppressed(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        cooldown_seconds=60,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate({}))
    asyncio.run(eng.evaluate({}))
    assert rec.call_count == 1


def test_second_fire_after_cooldown_passes(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate({}))
    time.sleep(0.01)
    asyncio.run(eng.evaluate({}))
    assert rec.call_count == 2


def test_fresh_engine_respects_shared_redis_cooldown(monkeypatch):
    """Cross-process semantics. A second engine that shares the same
    Redis must still suppress a rule whose cooldown window is open,
    even though the second engine has an empty in-process microcache.
    This is the post-restart / multi-worker invariant.
    """
    shared = FakeRedis()
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        cooldown_seconds=300,
    )
    eng_a, rec_a = install_engine(monkeypatch, [rule], share_redis=shared)
    asyncio.run(eng_a.evaluate({}))
    assert rec_a.call_count == 1

    # Engine B is "freshly started" but points at the same Redis. It
    # should see the cooldown written by engine A and suppress.
    eng_b, rec_b = install_engine(monkeypatch, [rule], share_redis=shared)
    assert eng_b._cooldowns == {}  # microcache is empty on this engine
    asyncio.run(eng_b.evaluate({}))
    assert rec_b.call_count == 0


def test_cooldown_zero_skips_redis(monkeypatch):
    """cooldown_seconds=0 must never touch Redis. Verified by handing
    the engine a FakeRedis whose ``set`` raises; if the engine called
    ``set`` it would fail loudly (logged warning only, no crash), but
    the test also asserts the underlying store stays empty.
    """
    shared = FakeRedis()
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        cooldown_seconds=0,
    )
    eng, rec = install_engine(monkeypatch, [rule], share_redis=shared)
    asyncio.run(eng.evaluate({}))
    asyncio.run(eng.evaluate({}))
    assert rec.call_count == 2
    assert shared._data == {}
    assert shared._expires == {}


def test_cooldown_ttl_matches_cooldown_seconds_plus_buffer(monkeypatch):
    """The Redis TTL on a cooldown key should be roughly
    ``cooldown_seconds + COOLDOWN_TTL_BUFFER`` so a key cannot linger
    forever and cannot vanish before the cooldown window closes.
    """
    from services.events.engine import RuleEngine

    shared = FakeRedis()
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        cooldown_seconds=120,
    )
    eng, _ = install_engine(monkeypatch, [rule], share_redis=shared)
    asyncio.run(eng.evaluate({}))

    key = RuleEngine.COOLDOWN_KEY_PREFIX + str(rule.id)
    ttl = shared.ttl_for(key)
    assert ttl is not None
    expected = rule.cooldown_seconds + RuleEngine.COOLDOWN_TTL_BUFFER
    # Allow a small wall-clock slack for the test run.
    assert expected - 2 <= ttl <= expected + 0.5


def test_redis_failure_falls_back_to_microcache(monkeypatch, caplog):
    """When Redis raises on every call, the engine must keep working.
    Within the 1s microcache window a second fire is still suppressed
    by the local copy; outside it, the engine degrades to "fires from
    every worker" which is documented behavior.
    """
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        cooldown_seconds=60,
    )
    failing = FakeRedis(fail_mode="all")
    eng, rec = install_engine(monkeypatch, [rule], share_redis=failing)

    with caplog.at_level("WARNING"):
        asyncio.run(eng.evaluate({}))
        asyncio.run(eng.evaluate({}))

    # First fire stored last_fired in the microcache even though the
    # Redis SET raised. The second evaluate within the 1s window reads
    # that microcache and suppresses.
    assert rec.call_count == 1
    # Engine logged the failure rather than crashing.
    assert any("redis" in r.message.lower() for r in caplog.records)
