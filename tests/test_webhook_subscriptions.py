import uuid
from types import SimpleNamespace

import pytest

from services.events import actions as actions_mod
from services.events.actions import dispatch_subscriptions


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        return _Result(self._rows)

    async def get(self, model, ident):
        return None  # skip status write-back in tests

    async def commit(self):
        pass


def _sub(**over):
    base = dict(
        id=uuid.uuid4(), name="s", url="http://hook", secret=None,
        active=True, rule_ids=None, camera_ids=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _patch(monkeypatch, subs):
    monkeypatch.setattr(actions_mod, "async_session", lambda: _Session(subs))
    delivered = []

    async def fake_deliver(method, url, payload, **kw):
        delivered.append({"url": url, "secret": kw.get("secret"), "payload": payload})
        return True, "status 200"

    monkeypatch.setattr(actions_mod, "deliver_signed", fake_deliver)
    return delivered


def _ctx():
    rule = SimpleNamespace(id=uuid.uuid4(), name="r")
    data = {"camera_id": str(uuid.uuid4()), "timestamp": "2026-06-01T00:00:00+00:00"}
    return rule, data


@pytest.mark.asyncio
async def test_dispatch_delivers_to_all_unfiltered(monkeypatch):
    delivered = _patch(monkeypatch, [_sub(), _sub()])
    rule, data = _ctx()
    await dispatch_subscriptions(data, rule, uuid.uuid4())
    assert len(delivered) == 2


@pytest.mark.asyncio
async def test_dispatch_respects_rule_filter(monkeypatch):
    rule, data = _ctx()
    match = _sub(rule_ids=[str(rule.id)])
    miss = _sub(rule_ids=[str(uuid.uuid4())])
    delivered = _patch(monkeypatch, [match, miss])
    await dispatch_subscriptions(data, rule, uuid.uuid4())
    assert len(delivered) == 1


@pytest.mark.asyncio
async def test_dispatch_respects_camera_filter(monkeypatch):
    rule, data = _ctx()
    miss = _sub(camera_ids=[str(uuid.uuid4())])
    delivered = _patch(monkeypatch, [miss])
    await dispatch_subscriptions(data, rule, uuid.uuid4())
    assert delivered == []


@pytest.mark.asyncio
async def test_dispatch_passes_secret(monkeypatch):
    rule, data = _ctx()
    delivered = _patch(monkeypatch, [_sub(secret="shh")])
    await dispatch_subscriptions(data, rule, uuid.uuid4())
    assert delivered[0]["secret"] == "shh"
