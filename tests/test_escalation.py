"""Unit tests for mid-run model escalation (G6, issue #132)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from services import escalation as esc


def _p(kind, model="m", active=True, pid=None, name=None):
    return SimpleNamespace(id=pid or uuid.uuid4(), kind=kind, default_model=model,
                           active=active, name=name or kind)


# ---- ranking -----------------------------------------------------------


def test_known_kinds_rank_cloud_above_local():
    assert esc.provider_rank(_p("anthropic")) < esc.provider_rank(_p("openai"))
    assert esc.provider_rank(_p("openai")) < esc.provider_rank(_p("ollama"))


def test_unknown_kinds_land_in_the_middle():
    assert esc.provider_rank(_p("some-new-vendor")) == esc.UNKNOWN_RANK
    assert esc.provider_rank(SimpleNamespace()) == esc.UNKNOWN_RANK


def test_kind_matching_ignores_case():
    assert esc.provider_rank(_p("Anthropic")) == esc.provider_rank(_p("anthropic"))


# ---- picking -----------------------------------------------------------


def test_picks_the_strongest_candidate_above_the_current_one():
    weak = _p("ollama")
    out = esc.pick_stronger(weak, [_p("openai"), _p("anthropic"), _p("ollama")])
    assert out.kind == "anthropic"


def test_never_picks_the_same_tier():
    # A second roll of the same dice is not an escalation.
    assert esc.pick_stronger(_p("openai"), [_p("openai")]) is None


def test_never_picks_something_weaker():
    assert esc.pick_stronger(_p("anthropic"), [_p("ollama"), _p("openai")]) is None


def test_never_picks_the_provider_it_is_escalating_from():
    same = _p("openai", pid="p1")
    assert esc.pick_stronger(same, [same]) is None


def test_skips_candidates_with_no_model_configured():
    assert esc.pick_stronger(_p("ollama"), [_p("anthropic", model=None)]) is None


def test_no_candidates_means_no_escalation():
    assert esc.pick_stronger(_p("ollama"), []) is None


# ---- resolution --------------------------------------------------------


class _FakeDB:
    def __init__(self, providers, by_id=None):
        self.providers = providers
        self.by_id = by_id or {}

    async def get(self, model, ident):
        return self.by_id.get(str(ident))

    async def execute(self, stmt):
        providers = [p for p in self.providers if p.active]

        class _S:
            def all(self_inner):
                return providers

        class _R:
            def scalars(self_inner):
                return _S()

        return _R()


def _patch_setting(monkeypatch, value):
    async def _get_setting(key, default=None):
        return value

    monkeypatch.setattr(esc, "get_setting", _get_setting)


@pytest.mark.asyncio
async def test_admin_override_beats_the_builtin_ranking(monkeypatch):
    forced_id = uuid.uuid4()
    forced = _p("some-new-vendor", pid=forced_id, name="House model")
    strongest = _p("anthropic")
    _patch_setting(monkeypatch, str(forced_id))
    db = _FakeDB([forced, strongest], {str(forced_id): forced})
    out = await esc.escalation_provider(db, _p("ollama"), "k")
    assert out is forced


@pytest.mark.asyncio
async def test_inactive_override_falls_back_to_the_ranking(monkeypatch):
    forced_id = uuid.uuid4()
    forced = _p("openai", pid=forced_id, active=False)
    strongest = _p("anthropic")
    _patch_setting(monkeypatch, str(forced_id))
    db = _FakeDB([forced, strongest], {str(forced_id): forced})
    out = await esc.escalation_provider(db, _p("ollama"), "k")
    assert out is strongest


@pytest.mark.asyncio
async def test_garbage_override_is_ignored(monkeypatch):
    strongest = _p("anthropic")
    _patch_setting(monkeypatch, "not-a-uuid")
    db = _FakeDB([strongest])
    assert await esc.escalation_provider(db, _p("ollama"), "k") is strongest


@pytest.mark.asyncio
async def test_no_override_uses_the_ranking(monkeypatch):
    _patch_setting(monkeypatch, None)
    db = _FakeDB([_p("openai"), _p("ollama")])
    out = await esc.escalation_provider(db, _p("ollama"), "k")
    assert out.kind == "openai"


@pytest.mark.asyncio
async def test_nothing_stronger_available_returns_none(monkeypatch):
    _patch_setting(monkeypatch, None)
    db = _FakeDB([_p("ollama")])
    assert await esc.escalation_provider(db, _p("anthropic"), "k") is None


@pytest.mark.asyncio
async def test_escalation_lookup_never_raises(monkeypatch):
    _patch_setting(monkeypatch, None)

    class _Boom:
        async def execute(self, stmt):
            raise RuntimeError("db is down")

    assert await esc.escalation_provider(_Boom(), _p("ollama"), "k") is None
