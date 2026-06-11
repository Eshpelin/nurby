"""Web ack / mute / snooze endpoint coverage.

These are the web counterparts to the Telegram inline buttons. The fakes
mirror tests/test_guardian_api.py's minimal async-session stand-in.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.api.routes import events as ev
from services.api.routes import rules as ru


class FakeDB:
    def __init__(self, objects=None):
        self._objs = {getattr(o, "id", None): o for o in (objects or [])}
        self.committed = 0

    async def get(self, model, oid):
        return self._objs.get(oid)

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        pass


def _user(role="viewer"):
    return SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True)


def _event(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        acked_at=None,
        acked_by_user_id=None,
        acked_via=None,
        acknowledged_at=None,
        muted_until=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _rule(**kw):
    defaults = dict(id=uuid.uuid4(), snoozed_until=None)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ── ack ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ack_sets_triad_and_legacy_mirror():
    user = _user()
    event = _event()
    db = FakeDB([event])
    out = await ev.ack_event(event.id, current_user=user, db=db)
    assert out.acked_at is not None
    assert out.acked_by_user_id == user.id
    assert out.acked_via == "web"
    assert out.acknowledged_at == out.acked_at


@pytest.mark.asyncio
async def test_ack_idempotent_preserves_first_acker():
    first = _user()
    event = _event(
        acked_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        acked_by_user_id=first.id,
        acked_via="telegram",
    )
    db = FakeDB([event])
    out = await ev.ack_event(event.id, current_user=_user(), db=db)
    assert out.acked_by_user_id == first.id
    assert out.acked_via == "telegram"
    assert db.committed == 0


@pytest.mark.asyncio
async def test_ack_404():
    with pytest.raises(ev.HTTPException) as ei:
        await ev.ack_event(uuid.uuid4(), current_user=_user(), db=FakeDB())
    assert ei.value.status_code == 404


# ── mute ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mute_sets_muted_until():
    event = _event()
    db = FakeDB([event])
    before = datetime.now(timezone.utc)
    await ev.mute_event(event.id, duration_seconds=600, _current_user=_user(), db=db)
    assert event.muted_until >= before + timedelta(seconds=599)
    assert db.committed == 1


@pytest.mark.asyncio
async def test_mute_404():
    with pytest.raises(ev.HTTPException) as ei:
        await ev.mute_event(uuid.uuid4(), duration_seconds=600, _current_user=_user(), db=FakeDB())
    assert ei.value.status_code == 404


# ── snooze / unsnooze ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snooze_sets_snoozed_until():
    rule = _rule()
    db = FakeDB([rule])
    before = datetime.now(timezone.utc)
    await ru.snooze_rule(rule.id, duration_seconds=3600, _current_user=_user(), db=db)
    assert rule.snoozed_until >= before + timedelta(seconds=3599)


@pytest.mark.asyncio
async def test_unsnooze_clears():
    rule = _rule(snoozed_until=datetime.now(timezone.utc) + timedelta(hours=1))
    db = FakeDB([rule])
    await ru.unsnooze_rule(rule.id, _current_user=_user(), db=db)
    assert rule.snoozed_until is None


@pytest.mark.asyncio
async def test_snooze_404():
    with pytest.raises(ru.HTTPException) as ei:
        await ru.snooze_rule(uuid.uuid4(), duration_seconds=3600, _current_user=_user(), db=FakeDB())
    assert ei.value.status_code == 404
