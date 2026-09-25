"""Best-effort usage estimates for camera VLM work."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from services.agent.budget import estimate_cost


# Conservative low-detail image allowance for the hosted vision APIs.
LOW_DETAIL_IMAGE_TOKENS = 765


@dataclass(frozen=True)
class PerceptionBudgetDecision:
    allowed: bool
    stage: str
    reason: str
    projected_cost_cents: int
    projected_tokens: int


def perception_budget_decision(
    *, used_cost_cents: int, used_tokens: int, estimated_cost_cents: int,
    estimated_tokens: int, cost_limit_cents: int = 0, token_limit: int = 0,
    warn_threshold_pct: int = 80,
) -> PerceptionBudgetDecision:
    """Apply the conservative camera-budget ladder before a VLM call.

    Zero limits disable that dimension.  The first production slice blocks
    only when the next call would cross a configured limit; callers can use
    ``stage`` to implement cheaper/local fallback later without changing the
    accounting contract.
    """
    projected_cost = max(0, int(used_cost_cents)) + max(0, int(estimated_cost_cents))
    projected_tokens = max(0, int(used_tokens)) + max(0, int(estimated_tokens))
    cost_pct = (projected_cost * 100 / cost_limit_cents) if cost_limit_cents else 0
    token_pct = (projected_tokens * 100 / token_limit) if token_limit else 0
    peak_pct = max(cost_pct, token_pct)
    blocked_cost = cost_limit_cents > 0 and projected_cost > cost_limit_cents
    blocked_tokens = token_limit > 0 and projected_tokens > token_limit
    if blocked_cost or blocked_tokens:
        dimensions = []
        if blocked_cost:
            dimensions.append(f"cost budget {cost_limit_cents}c")
        if blocked_tokens:
            dimensions.append(f"token budget {token_limit}")
        return PerceptionBudgetDecision(
            False, "blocked", "Next VLM call would exceed " + " and ".join(dimensions),
            projected_cost, projected_tokens,
        )
    stage = "warn" if peak_pct >= max(1, warn_threshold_pct) else "normal"
    return PerceptionBudgetDecision(
        True, stage,
        f"Projected perception usage is {int(peak_pct)}% of the configured limit." if stage == "warn" else "",
        projected_cost, projected_tokens,
    )


def combine_perception_usage(
    ledger_cost_cents: int,
    ledger_tokens: int,
    pass_cost_cents: int,
    pass_tokens: int,
) -> tuple[int, int]:
    """Combine the two camera-scoped VLM accounting stores.

    ``PerceptionVlmUsage`` covers rule/action/analyzer calls while
    ``ObservationVlmPass`` is the append-only ledger for captions and idle
    enrichment.  They are intentionally kept separate because the usage
    report presents them differently, but both must consume the same camera
    budget.  Clamp null/negative values defensively so old or partially
    migrated rows cannot make a budget appear lower than it is.
    """
    return (
        max(0, int(ledger_cost_cents or 0)) + max(0, int(pass_cost_cents or 0)),
        max(0, int(ledger_tokens or 0)) + max(0, int(pass_tokens or 0)),
    )


async def check_perception_budget(
    camera_id: str | None, *, estimated_cost_cents: int, estimated_tokens: int,
) -> PerceptionBudgetDecision:
    """Read today's camera ledger and decide whether one call may start."""
    from shared.app_settings import get_setting
    from shared.database import async_session
    from shared.models import Observation, ObservationVlmPass, PerceptionVlmUsage

    cost_limit = int(await get_setting("perception_daily_cost_budget_cents") or 0)
    token_limit = int(await get_setting("perception_daily_token_budget") or 0)
    warn_pct = int(await get_setting("perception_budget_warn_threshold_pct") or 80)
    if not camera_id or (cost_limit <= 0 and token_limit <= 0):
        return perception_budget_decision(
            used_cost_cents=0, used_tokens=0,
            estimated_cost_cents=estimated_cost_cents, estimated_tokens=estimated_tokens,
            cost_limit_cents=cost_limit, token_limit=token_limit, warn_threshold_pct=warn_pct,
        )
    try:
        camera_uuid = uuid.UUID(str(camera_id))
    except (TypeError, ValueError, AttributeError):
        return PerceptionBudgetDecision(True, "normal", "", estimated_cost_cents, estimated_tokens)
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as db:
        ledger_row = (await db.execute(
            select(
                func.coalesce(func.sum(PerceptionVlmUsage.cost_cents), 0),
                func.coalesce(func.sum(PerceptionVlmUsage.tokens_in + PerceptionVlmUsage.tokens_out), 0),
            ).where(
                PerceptionVlmUsage.camera_id == camera_uuid,
                PerceptionVlmUsage.created_at >= start,
            )
        )).one()
        pass_row = (await db.execute(
            select(
                func.coalesce(func.sum(ObservationVlmPass.cost_cents), 0),
                func.coalesce(func.sum(ObservationVlmPass.tokens_in + ObservationVlmPass.tokens_out), 0),
            )
            .join(Observation, Observation.id == ObservationVlmPass.observation_id)
            .where(
                Observation.camera_id == camera_uuid,
                ObservationVlmPass.created_at >= start,
            )
        )).one()
    used_cost_cents, used_tokens = combine_perception_usage(
        ledger_row[0], ledger_row[1], pass_row[0], pass_row[1],
    )
    return perception_budget_decision(
        used_cost_cents=used_cost_cents, used_tokens=used_tokens,
        estimated_cost_cents=estimated_cost_cents, estimated_tokens=estimated_tokens,
        cost_limit_cents=cost_limit, token_limit=token_limit, warn_threshold_pct=warn_pct,
    )


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
