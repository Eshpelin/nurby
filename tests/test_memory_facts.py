"""Memory: remember tool + household facts API (#286)."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from services.agent.tools import setup_tools as st
from services.api.routes import household as hh


def _run(coro):
    return asyncio.run(coro)


# ── remember tool (confirm gate) ──

def test_remember_returns_confirm_proposal():
    out = _run(st.remember({"db": None, "user": None}, fact="the kids get home at 3:30pm"))
    assert out["ok"] is True
    ca = out["client_action"]
    assert ca["kind"] == "remember_fact"
    assert ca["method"] == "POST" and ca["path"] == "/api/household/facts"
    assert ca["body"] == {"text": "the kids get home at 3:30pm", "kind": "note"}
    assert "confirm" in out["message_for_user"].lower()


def test_remember_empty_is_rejected():
    out = _run(st.remember({"db": None, "user": None}, fact="   "))
    assert out["ok"] is False


def test_remember_is_registered():
    from services.agent.tools import TOOL_REGISTRY
    entry = next((t for t in TOOL_REGISTRY if t["name"] == "remember"), None)
    assert entry is not None
    # It carries no side-effect write; the confirm gate does the write.
    assert entry["side_effect"] == "read"


# ── facts API ──

class _FactsDB:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one
        self.added = []
        self.deleted = []

    def add(self, o):
        self.added.append(o)

    async def commit(self):
        pass

    async def refresh(self, o):
        pass

    async def get(self, model, ident):
        return self.one

    async def delete(self, o):
        self.deleted.append(o)

    async def execute(self, stmt):
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _fact(**kw):
    base = dict(
        id=uuid.uuid4(), text="dad's car is grey", subject_key="user:abc", kind="note",
        source="user", status="established", pinned=False, evidence_count=0,
        created_at=None, last_confirmed_at=None, archived_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_create_fact_is_user_sourced_and_established():
    db = _FactsDB()
    out = _run(hh.create_fact(hh.FactCreate(text="remember this"), SimpleNamespace(id=uuid.uuid4()), db))
    assert out["source"] == "user"
    assert out["status"] == "established" and out["enabled"] is True
    assert db.added and db.added[0].source == "user"


def test_update_fact_edit_sets_text():
    f = _fact()
    db = _FactsDB(one=f)
    out = _run(hh.update_fact(f.id, hh.FactUpdate(text="dad's car is silver"), SimpleNamespace(id=uuid.uuid4()), db))
    assert f.text == "dad's car is silver"
    assert out["text"] == "dad's car is silver"


def test_disable_fact_archives_it():
    f = _fact(status="established")
    db = _FactsDB(one=f)
    out = _run(hh.update_fact(f.id, hh.FactUpdate(enabled=False), SimpleNamespace(id=uuid.uuid4()), db))
    assert f.status == "archived" and out["enabled"] is False


def test_enable_fact_restores_it():
    f = _fact(status="archived")
    db = _FactsDB(one=f)
    _run(hh.update_fact(f.id, hh.FactUpdate(enabled=True), SimpleNamespace(id=uuid.uuid4()), db))
    assert f.status == "established" and f.archived_at is None


def test_update_missing_fact_404():
    db = _FactsDB(one=None)
    with pytest.raises(Exception) as e:
        _run(hh.update_fact(uuid.uuid4(), hh.FactUpdate(text="x"), SimpleNamespace(id=uuid.uuid4()), db))
    assert "404" in str(e.value) or "not found" in str(e.value)


def test_delete_fact():
    f = _fact()
    db = _FactsDB(one=f)
    _run(hh.delete_fact(f.id, SimpleNamespace(id=uuid.uuid4()), db))
    assert db.deleted == [f]


def test_list_facts_shapes_source_and_enabled():
    db = _FactsDB(rows=[_fact(source="user", status="established"), _fact(source="agent", status="archived")])
    out = _run(hh.list_facts(True, SimpleNamespace(id=uuid.uuid4()), db))
    assert {r["source"] for r in out} == {"user", "agent"}
    assert out[0]["enabled"] is True and out[1]["enabled"] is False
