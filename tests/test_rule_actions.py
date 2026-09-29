"""Tests for action-chain validation and condition evaluation."""

import pytest

from shared.schemas import RuleCreate


def _mkrule(actions):
    return RuleCreate(
        name="test",
        trigger_pattern={"type": "any"},
        actions=actions,
    )


def test_vlm_call_output_then_webhook_reference_ok():
    actions = [
        {
            "type": "vlm_call",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "prompt": "rate the threat",
            "output": "threat",
            "response_schema": {
                "type": "object",
                "properties": {"level": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
        {
            "type": "webhook",
            "url": "https://example.com/hook",
            "payload_template": {"level": "{{vars.threat.level}}"},
        },
    ]
    rule = _mkrule(actions)
    assert len(rule.actions) == 2


def test_forward_reference_rejected():
    actions = [
        {
            "type": "webhook",
            "url": "https://example.com/{{vars.threat.level}}",
        },
        {
            "type": "vlm_call",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "prompt": "rate",
            "output": "threat",
        },
    ]
    with pytest.raises(Exception) as exc:
        _mkrule(actions)
    assert "threat" in str(exc.value)


def test_unknown_output_rejected():
    actions = [
        {
            "type": "vlm_call", "provider": "openai", "model": "m",
            "prompt": "p", "output": "foo",
        },
        {
            "type": "email", "to": "a@b.co",
            "subject": "s", "body": "{{vars.bar.x}}",
        },
    ]
    with pytest.raises(Exception) as exc:
        _mkrule(actions)
    assert "bar" in str(exc.value)


def test_unknown_action_type_rejected():
    with pytest.raises(Exception):
        _mkrule([{"type": "dance"}])


def test_schema_top_level_key_check():
    actions = [
        {
            "type": "vlm_call", "provider": "openai", "model": "m", "prompt": "p",
            "output": "o",
            "response_schema": {"type": "object", "properties": {"level": {"type": "string"}}},
        },
        {
            "type": "webhook", "url": "http://x",
            "payload_template": {"val": "{{vars.o.nope}}"},
        },
    ]
    with pytest.raises(Exception) as exc:
        _mkrule(actions)
    assert "nope" in str(exc.value)


def test_condition_evaluated_by_runner(monkeypatch):
    import asyncio

    from services.events import actions as actions_mod

    calls = []

    async def fake_webhook(action, obs, rule, event_id, ctx):
        calls.append(action["url"])

    async def fake_update(*a, **kw):
        pass

    monkeypatch.setattr(actions_mod, "_execute_webhook", fake_webhook)
    monkeypatch.setattr(actions_mod, "_update_event_status", fake_update)

    class R:
        id = __import__("uuid").uuid4()
        name = "r"

    async def run():
        obs = {"vars": {"out": {"level": "high"}}}
        skip_action = {
            "type": "webhook", "url": "skip",
            "condition": "vars.out.level == 'low'",
        }
        go_action = {
            "type": "webhook", "url": "go",
            "condition": "vars.out.level == 'high'",
        }
        await actions_mod.execute_action(skip_action, obs, R(), R.id)
        await actions_mod.execute_action(go_action, obs, R(), R.id)

    asyncio.run(run())
    assert calls == ["go"]


def test_synthetic_action_outcome_is_recorded():
    from services.events import actions as actions_mod

    observation = {"_test_alert": True, "_test_action_index": 2}
    actions_mod._set_test_result(observation, "failed", "provider rejected request")
    assert observation["_test_results"]["2"] == {
        "status": "failed",
        "detail": "provider rejected request",
    }


def test_normal_action_does_not_record_synthetic_outcome():
    from services.events import actions as actions_mod

    observation = {"_test_action_index": 2}
    actions_mod._set_test_result(observation, "success")
    assert "_test_results" not in observation


def test_chained_output_writes_vars(monkeypatch):
    import asyncio

    from services.events import actions as actions_mod

    async def fake_call_vlm(*args, **kwargs):
        return '{"level": "high", "reason": "ok"}'

    async def fake_update(*a, **kw):
        pass

    class FakeProvider:
        api_key = "k"
        base_url = "http://x"
        default_model = "m"

    async def fake_provider(kind):
        return FakeProvider()

    monkeypatch.setattr(actions_mod, "_call_vlm", fake_call_vlm)
    monkeypatch.setattr(actions_mod, "_get_provider_by_kind", fake_provider)
    monkeypatch.setattr(actions_mod, "_update_event_status", fake_update)

    class R:
        id = __import__("uuid").uuid4()
        name = "r"

    async def run():
        obs = {"vars": {}}
        action = {
            "type": "vlm_call",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "prompt": "p",
            "output": "threat",
            "response_schema": {
                "type": "object",
                "properties": {"level": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["level", "reason"],
            },
        }
        await actions_mod.execute_action(action, obs, R(), R.id)
        return obs["vars"]

    vars_bag = asyncio.run(run())
    assert vars_bag["threat"]["level"] == "high"


def test_local_fallback_only_applies_to_hosted_cost_budget():
    from services.events import actions as actions_mod
    from services.perception.usage import PerceptionBudgetDecision

    cost_block = PerceptionBudgetDecision(False, "blocked", "Next VLM call would exceed cost budget 10c", 11, 1)
    token_block = PerceptionBudgetDecision(False, "blocked", "Next VLM call would exceed token budget 10", 1, 11)
    combined_block = PerceptionBudgetDecision(False, "blocked", "Next VLM call would exceed cost budget 10c and token budget 10", 11, 11)

    assert actions_mod._local_fallback_allowed("openai", cost_block)
    assert not actions_mod._local_fallback_allowed("openai", token_block)
    assert not actions_mod._local_fallback_allowed("openai", combined_block)
    assert not actions_mod._local_fallback_allowed("ollama", cost_block)


@pytest.mark.asyncio
async def test_blocked_hosted_rule_uses_local_provider(monkeypatch):
    from services.events import actions as actions_mod
    from services.perception.usage import PerceptionBudgetDecision

    class Provider:
        def __init__(self, kind):
            self.kind = kind
            self.default_model = f"{kind}-model"
            self.api_key = "key"
            self.base_url = "http://provider"

    hosted = Provider("openai")
    local = Provider("ollama")
    calls = []

    async def provider_for(kind):
        return local if kind == "ollama" else hosted

    async def fake_call(kind, provider, *args, **kwargs):
        calls.append((kind, provider.kind))
        return "local answer"

    async def no_op(*args, **kwargs):
        return None

    async def blocked(*args, **kwargs):
        return PerceptionBudgetDecision(False, "blocked", "Next VLM call would exceed cost budget 10c", 11, 1)

    monkeypatch.setattr(actions_mod, "_get_provider_by_kind", provider_for)
    monkeypatch.setattr(actions_mod, "_call_vlm", fake_call)
    monkeypatch.setattr(actions_mod, "check_perception_budget", blocked)
    monkeypatch.setattr(actions_mod, "record_vlm_usage", no_op)
    monkeypatch.setattr(actions_mod, "_update_event_status", no_op)

    class Rule:
        id = __import__("uuid").uuid4()
        name = "budget fallback"

    observation = {"camera_id": str(__import__("uuid").uuid4()), "vars": {}}
    await actions_mod.execute_action(
        {"type": "vlm_call", "provider": "openai", "prompt": "answer", "output": "answer"},
        observation,
        Rule(),
        Rule.id,
    )

    assert calls == [("ollama", "ollama")]
    assert observation["vars"]["answer"] == "local answer"
