"""Tests for optional reasoning / "thinking" model support (issue #41).

Three concerns are exercised:

1. shared.reasoning pure helpers — request-param building (off by
   default, opt-in shapes), thinking-block stripping, reasoning-token
   reporting.
2. The captions / agent answers never contain reasoning text — the
   Anthropic VLM and agent call sites strip thinking blocks.
3. Token accounting includes reasoning tokens (Anthropic folds them
   into output_tokens; OpenAI nests reasoning_tokens under
   completion_tokens_details, and we floor tokens_out at that).

Provider config is supplied via SimpleNamespace so the suite stays
DB-free and proves getattr(..., None) defaults keep old rows working.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from shared import reasoning as R


def _run(coro):
    return asyncio.run(coro)


def _provider(**kw) -> SimpleNamespace:
    base = {
        "name": "p",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "k",
        "default_model": "claude-opus-4-8",
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── shared.reasoning: request-param building ─────────────────────────


def test_anthropic_thinking_off_by_default():
    # A provider with no thinking attrs at all (old row / test fake).
    p = SimpleNamespace(name="p")
    assert R.anthropic_thinking_params(p, 4096) == {}


def test_anthropic_thinking_explicit_off():
    p = _provider(anthropic_thinking="off")
    assert R.anthropic_thinking_params(p, 4096) == {}


def test_anthropic_thinking_adaptive():
    p = _provider(anthropic_thinking="adaptive")
    assert R.anthropic_thinking_params(p, 4096) == {"thinking": {"type": "adaptive"}}


def test_anthropic_thinking_enabled_uses_budget():
    p = _provider(anthropic_thinking="enabled", anthropic_thinking_budget_tokens=2000)
    out = R.anthropic_thinking_params(p, 8000)
    assert out == {"thinking": {"type": "enabled", "budget_tokens": 2000}}


def test_anthropic_thinking_enabled_floors_to_min_budget():
    # Below Anthropic's 1024 floor -> bumped up to 1024.
    p = _provider(anthropic_thinking="enabled", anthropic_thinking_budget_tokens=10)
    out = R.anthropic_thinking_params(p, 8000)
    assert out["thinking"]["budget_tokens"] == 1024


def test_anthropic_thinking_budget_clamped_below_max_tokens():
    # budget must be < max_tokens; here max leaves room so it shrinks.
    p = _provider(anthropic_thinking="enabled", anthropic_thinking_budget_tokens=8000)
    out = R.anthropic_thinking_params(p, 4096)
    assert out["thinking"]["type"] == "enabled"
    assert out["thinking"]["budget_tokens"] < 4096


def test_anthropic_thinking_falls_back_to_adaptive_when_cap_too_small():
    # max_tokens too small to house any fixed budget -> adaptive.
    p = _provider(anthropic_thinking="enabled", anthropic_thinking_budget_tokens=8000)
    out = R.anthropic_thinking_params(p, 512)
    assert out == {"thinking": {"type": "adaptive"}}


def test_openai_reasoning_off_by_default():
    p = SimpleNamespace(name="p")
    assert R.openai_reasoning_params(p) == {}


def test_openai_reasoning_effort_emitted():
    p = _provider(kind="openai", openai_reasoning_effort="high")
    assert R.openai_reasoning_params(p) == {"reasoning_effort": "high"}


def test_openai_reasoning_invalid_value_ignored():
    p = _provider(kind="openai", openai_reasoning_effort="ultra")
    assert R.openai_reasoning_params(p) == {}


# ── shared.reasoning: stripping reasoning from output ────────────────


def test_anthropic_visible_text_drops_thinking_blocks():
    blocks = [
        {"type": "thinking", "thinking": "the user wants X, let me reason..."},
        {"type": "text", "text": "A person is at the door."},
    ]
    assert R.anthropic_visible_text(blocks) == "A person is at the door."


def test_anthropic_visible_text_drops_redacted_thinking():
    blocks = [
        {"type": "redacted_thinking", "data": "ENCRYPTED"},
        {"type": "text", "text": "Visible answer."},
    ]
    assert R.anthropic_visible_text(blocks) == "Visible answer."


def test_anthropic_visible_text_handles_empty():
    assert R.anthropic_visible_text(None) == ""
    assert R.anthropic_visible_text([]) == ""


def test_is_thinking_block():
    assert R.is_thinking_block("thinking") is True
    assert R.is_thinking_block("redacted_thinking") is True
    assert R.is_thinking_block("text") is False
    assert R.is_thinking_block(None) is False


# ── shared.reasoning: reasoning-token reporting ──────────────────────


def test_openai_reasoning_tokens_reported():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 500,
        "completion_tokens_details": {"reasoning_tokens": 320},
    }
    assert R.openai_reasoning_tokens(usage) == 320


def test_openai_reasoning_tokens_absent_is_zero():
    assert R.openai_reasoning_tokens({"completion_tokens": 10}) == 0
    assert R.openai_reasoning_tokens(None) == 0


# ── VLM: anthropic caption strips thinking ───────────────────────────


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHTTP:
    """Stand-in for the VLMClient's stored httpx client."""

    def __init__(self, payload, sink):
        self._payload = payload
        self._sink = sink

    async def post(self, url, headers=None, json=None, timeout=None):
        self._sink["url"] = url
        self._sink["body"] = json
        return _FakeHTTPResponse(self._payload)


def _vlm_with_response(payload, sink):
    from services.perception.vlm import VLMClient

    client = VLMClient()
    fake = _FakeHTTP(payload, sink)

    async def _get_http():
        return fake

    client._get_http = _get_http  # type: ignore[assignment]
    return client


def test_vlm_anthropic_caption_excludes_thinking():
    # Response leads with a thinking block, then the visible caption.
    payload = {
        "content": [
            {"type": "thinking", "thinking": "let me count the people in frame"},
            {"type": "text", "text": "Two people walking toward the gate."},
        ],
        "usage": {"input_tokens": 50, "output_tokens": 400},
    }
    sink: dict = {}
    client = _vlm_with_response(payload, sink)
    provider = _provider(anthropic_thinking="adaptive")

    out = _run(client._call_anthropic("b64img", "describe", provider, "sys", 1024))
    assert out == "Two people walking toward the gate."
    assert "reason" not in out and "count the people" not in out
    # The opt-in thinking param was wired into the request body.
    assert sink["body"]["thinking"] == {"type": "adaptive"}


def test_vlm_anthropic_default_has_no_thinking_param():
    payload = {
        "content": [{"type": "text", "text": "Quiet scene."}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    sink: dict = {}
    client = _vlm_with_response(payload, sink)
    provider = _provider()  # no thinking config

    out = _run(client._call_anthropic("b64img", "describe", provider, "sys", 1024))
    assert out == "Quiet scene."
    # Default behavior unchanged: no thinking field in the request.
    assert "thinking" not in sink["body"]


def test_vlm_openai_reasoning_effort_wired_into_request():
    # describe() builds the OpenAI payload then calls _call_openai; verify
    # the reasoning_effort lands in the request body when opted in.
    captured: dict = {}

    async def fake_call_openai(self, b64, prompt, provider, system_prompt, output_cap):
        # mirror the body-construction in the real method
        payload = {"model": "x", "messages": []}
        from shared.reasoning import openai_reasoning_params

        payload.update(openai_reasoning_params(provider))
        captured["body"] = payload
        return "ok"

    from services.perception.vlm import VLMClient

    provider = _provider(kind="openai", openai_reasoning_effort="medium")
    client = VLMClient()
    import types as _t

    client._call_openai = _t.MethodType(fake_call_openai, client)  # type: ignore
    out = _run(
        client.describe(
            frame=np.zeros((4, 4, 3), dtype=np.uint8),
            detections=[],
            provider=provider,
        )
    )
    assert out == "ok"
    assert captured["body"]["reasoning_effort"] == "medium"


# ── Agent llm.py: anthropic answer strips thinking + counts tokens ───


class _FakeAgentClient:
    def __init__(self, payload, sink):
        self._payload = payload
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, headers=None, json=None):
        self._sink["body"] = json
        return _FakeHTTPResponse(self._payload)


def test_agent_anthropic_answer_excludes_thinking_counts_output(monkeypatch):
    from services.agent import llm as llm_mod

    payload = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "internal chain of thought"},
            {"type": "text", "text": "The cat was last seen at the back door."},
        ],
        # Anthropic folds reasoning into output_tokens — the budget must
        # count this full number, not just the visible answer's tokens.
        "usage": {"input_tokens": 120, "output_tokens": 900},
        "id": "msg_1",
    }
    sink: dict = {}
    monkeypatch.setattr(
        llm_mod.httpx, "AsyncClient", lambda *a, **kw: _FakeAgentClient(payload, sink)
    )

    provider = _provider(anthropic_thinking="adaptive")
    resp = _run(
        llm_mod._call_anthropic(
            provider, "claude-opus-4-8", "sys", [{"role": "user", "content": "hi"}],
            [], 2048, False, None,
        )
    )
    assert resp.text == "The cat was last seen at the back door."
    assert "chain of thought" not in resp.text
    # Reasoning tokens are included in tokens_out (no undercount).
    assert resp.tokens_out == 900
    assert resp.tokens_in == 120
    # Opt-in thinking param wired into request body.
    assert sink["body"]["thinking"] == {"type": "adaptive"}


def test_agent_anthropic_default_no_thinking_param(monkeypatch):
    from services.agent import llm as llm_mod

    payload = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "answer"}],
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }
    sink: dict = {}
    monkeypatch.setattr(
        llm_mod.httpx, "AsyncClient", lambda *a, **kw: _FakeAgentClient(payload, sink)
    )
    provider = _provider()  # no thinking config
    resp = _run(
        llm_mod._call_anthropic(
            provider, "claude-opus-4-8", "sys", [{"role": "user", "content": "hi"}],
            [], 2048, False, None,
        )
    )
    assert resp.text == "answer"
    assert "thinking" not in sink["body"]


def test_agent_openai_floors_output_at_reasoning_tokens(monkeypatch):
    from services.agent import llm as llm_mod

    # Pathological usage: completion_tokens reported lower than
    # reasoning_tokens. tokens_out must not undercount reasoning.
    payload = {
        "choices": [
            {"message": {"content": "done", "tool_calls": []}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": 30,
            "completion_tokens": 100,
            "completion_tokens_details": {"reasoning_tokens": 250},
        },
        "id": "cmpl_1",
    }
    sink: dict = {}
    monkeypatch.setattr(
        llm_mod.httpx, "AsyncClient", lambda *a, **kw: _FakeAgentClient(payload, sink)
    )
    provider = _provider(kind="openai", base_url="https://api.openai.com",
                         openai_reasoning_effort="high")
    resp = _run(
        llm_mod._call_openai_like(
            provider, "gpt-5", "sys", [{"role": "user", "content": "hi"}],
            [], 2048, False, None,
        )
    )
    assert resp.text == "done"
    # max(completion=100, reasoning=250) == 250
    assert resp.tokens_out == 250
    # reasoning_effort wired into the OpenAI request body.
    assert sink["body"]["reasoning_effort"] == "high"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
