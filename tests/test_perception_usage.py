from types import SimpleNamespace

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
