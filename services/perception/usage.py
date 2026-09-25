"""Best-effort usage estimates for camera VLM work."""

from __future__ import annotations

import math

from services.agent.budget import estimate_cost


# Conservative low-detail image allowance for the hosted vision APIs.
LOW_DETAIL_IMAGE_TOKENS = 765


def estimate_vlm_usage(
    provider,
    *,
    system_prompt: str | None,
    user_prompt: str | None,
    output_text: str | None,
    image_tokens: int = LOW_DETAIL_IMAGE_TOKENS,
) -> tuple[int, int, int]:
    """Return ``(input_tokens, output_tokens, cost_cents)``."""
    input_chars = len(system_prompt or "") + len(user_prompt or "")
    tokens_in = max(1, math.ceil(input_chars / 4) + max(0, image_tokens))
    tokens_out = max(0, math.ceil(len(output_text or "") / 4))
    cost = estimate_cost(
        getattr(provider, "kind", None),
        getattr(provider, "default_model", None),
        tokens_in,
        tokens_out,
    )
    return tokens_in, tokens_out, cost
