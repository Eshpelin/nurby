from types import SimpleNamespace

import pytest

import services.perception.usage as usage_module
from services.perception.usage import estimate_vlm_usage


def test_local_vlm_usage_is_free_but_keeps_token_estimates():
    provider = SimpleNamespace(kind="ollama", default_model="llava")

    tokens_in, tokens_out, cost = estimate_vlm_usage(
        provider,
        system_prompt="Describe the frame.",
        user_prompt="There is a person at the door.",
        output_text="A person is standing at the door.",
    )

    assert tokens_in > 765
    assert tokens_out > 0
    assert cost == 0


def test_hosted_vlm_usage_uses_conservative_estimated_pricing():
    provider = SimpleNamespace(kind="openai", default_model="gpt-4o")

    tokens_in, tokens_out, cost = estimate_vlm_usage(
        provider,
        system_prompt="system",
        user_prompt="prompt",
        output_text="reply",
    )

    assert tokens_in == 768
    assert tokens_out == 2
    assert cost == 1


@pytest.mark.asyncio
async def test_record_vlm_usage_preserves_native_counters(monkeypatch):
    rows = []

    class FakeUsage:
        def __init__(self, **kwargs):
            rows.append(kwargs)

    class FakeDb:
        def add(self, row):
            assert row is not None

        async def commit(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return FakeDb()

        async def __aexit__(self, *_args):
            return None

    import shared.database
    import shared.models

    monkeypatch.setattr(shared.database, "async_session", lambda: FakeSession())
    monkeypatch.setattr(shared.models, "PerceptionVlmUsage", FakeUsage)

    await usage_module.record_vlm_usage(
        SimpleNamespace(kind="openai", default_model="gpt-4o"),
        workload="agent_analyzer",
        system_prompt="estimated prompt that should not win",
        user_prompt="prompt",
        output_text="reply",
        actual_tokens_in=123,
        actual_tokens_out=17,
        actual_cost_cents=9,
    )

    assert rows == [{
        "camera_id": None,
        "rule_id": None,
        "event_id": None,
        "provider_id": None,
        "provider_name": None,
        "model": "gpt-4o",
        "workload": "agent_analyzer",
        "tokens_in": 123,
        "tokens_out": 17,
        "cost_cents": 9,
        "estimated": False,
        "succeeded": True,
    }]


@pytest.mark.asyncio
async def test_record_vlm_usage_accepts_native_tokens_when_cost_is_estimated(monkeypatch):
    rows = []

    class FakeUsage:
        def __init__(self, **kwargs):
            rows.append(kwargs)

    class FakeDb:
        def add(self, row):
            assert row is not None

        async def commit(self):
            return None

    class FakeSession:
        async def __aenter__(self):
            return FakeDb()

        async def __aexit__(self, *_args):
            return None

    import shared.database
    import shared.models

    monkeypatch.setattr(shared.database, "async_session", lambda: FakeSession())
    monkeypatch.setattr(shared.models, "PerceptionVlmUsage", FakeUsage)

    await usage_module.record_vlm_usage(
        SimpleNamespace(kind="google", default_model="gemini-2.0-flash"),
        workload="daily_digest",
        system_prompt="system",
        user_prompt="prompt",
        output_text="reply",
        actual_tokens_in=44,
        actual_tokens_out=8,
    )

    assert rows[0]["tokens_in"] == 44
    assert rows[0]["tokens_out"] == 8
    assert rows[0]["estimated"] is True
