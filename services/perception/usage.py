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
    model: str | None = None,
    image_tokens: int = LOW_DETAIL_IMAGE_TOKENS,
) -> tuple[int, int, int]:
    """Return ``(input_tokens, output_tokens, cost_cents)``."""
    input_chars = len(system_prompt or "") + len(user_prompt or "")
    tokens_in = max(1, math.ceil(input_chars / 4) + max(0, image_tokens))
    tokens_out = max(0, math.ceil(len(output_text or "") / 4))
    cost = estimate_cost(
        getattr(provider, "kind", None),
        model or getattr(provider, "default_model", None),
        tokens_in,
        tokens_out,
    )
    return tokens_in, tokens_out, cost


async def record_vlm_usage(
    provider,
    *,
    workload: str,
    system_prompt: str | None,
    user_prompt: str | None,
    output_text: str | None,
    camera_id: str | None = None,
    rule_id: str | None = None,
    event_id: str | None = None,
    model: str | None = None,
    image_tokens: int = LOW_DETAIL_IMAGE_TOKENS,
    succeeded: bool = True,
) -> None:
    """Persist one best-effort usage row without affecting perception."""
    import uuid

    from shared.database import async_session
    from shared.models import PerceptionVlmUsage

    try:
        tokens_in, tokens_out, cost_cents = estimate_vlm_usage(
            provider,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_text=output_text,
            model=model,
            image_tokens=image_tokens,
        )
        def parse(value: str | None):
            try:
                return uuid.UUID(str(value)) if value else None
            except (TypeError, ValueError, AttributeError):
                return None

        async with async_session() as db:
            db.add(PerceptionVlmUsage(
                camera_id=parse(camera_id),
                rule_id=parse(rule_id),
                event_id=parse(event_id),
                provider_id=getattr(provider, "id", None),
                provider_name=getattr(provider, "name", None),
                model=model or getattr(provider, "default_model", None),
                workload=workload,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_cents=cost_cents,
                succeeded=succeeded,
            ))
            await db.commit()
    except Exception:
        # A usage ledger must never turn a camera alert into a failed alert.
        return
