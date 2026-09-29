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
    rule_id: str | None = None,
) -> PerceptionBudgetDecision:
    """Read today's camera and optional rule ledgers before one call starts."""
    from shared.app_settings import get_setting
    from shared.database import async_session
    from shared.models import Observation, ObservationVlmPass, PerceptionVlmUsage

    cost_limit = int(await get_setting("perception_daily_cost_budget_cents") or 0)
    token_limit = int(await get_setting("perception_daily_token_budget") or 0)
    rule_cost_limit = int(await get_setting("perception_daily_cost_budget_cents_per_rule") or 0)
    rule_token_limit = int(await get_setting("perception_daily_token_budget_per_rule") or 0)
    warn_pct = int(await get_setting("perception_budget_warn_threshold_pct") or 80)
    if not camera_id or (
        cost_limit <= 0 and token_limit <= 0 and (
            not rule_id or (rule_cost_limit <= 0 and rule_token_limit <= 0)
        )
    ):
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
    decision = perception_budget_decision(
        used_cost_cents=used_cost_cents, used_tokens=used_tokens,
        estimated_cost_cents=estimated_cost_cents, estimated_tokens=estimated_tokens,
        cost_limit_cents=cost_limit, token_limit=token_limit, warn_threshold_pct=warn_pct,
    )
    if rule_id and (rule_cost_limit > 0 or rule_token_limit > 0):
        try:
            rule_uuid = uuid.UUID(str(rule_id))
        except (TypeError, ValueError, AttributeError):
            rule_uuid = None
        if rule_uuid is not None:
            async with async_session() as db:
                rule_row = (await db.execute(
                    select(
                        func.coalesce(func.sum(PerceptionVlmUsage.cost_cents), 0),
                        func.coalesce(func.sum(PerceptionVlmUsage.tokens_in + PerceptionVlmUsage.tokens_out), 0),
                    ).where(
                        PerceptionVlmUsage.rule_id == rule_uuid,
                        PerceptionVlmUsage.created_at >= start,
                    )
                )).one()
            rule_decision = perception_budget_decision(
                used_cost_cents=rule_row[0], used_tokens=rule_row[1],
                estimated_cost_cents=estimated_cost_cents,
                estimated_tokens=estimated_tokens,
                cost_limit_cents=rule_cost_limit,
                token_limit=rule_token_limit,
                warn_threshold_pct=warn_pct,
            )
            if rule_decision.stage in {"warn", "blocked"}:
                await _emit_budget_notification(camera_uuid, rule_decision, rule_uuid)
            if not rule_decision.allowed:
                return PerceptionBudgetDecision(
                    False,
                    "blocked",
                    f"Rule {rule_uuid} budget reached: {rule_decision.reason}",
                    rule_decision.projected_cost_cents,
                    rule_decision.projected_tokens,
                )
    if decision.stage in {"warn", "blocked"}:
        await _emit_budget_notification(camera_uuid, decision)
    return decision


async def _emit_budget_notification(
    camera_id: uuid.UUID,
    decision: PerceptionBudgetDecision,
    rule_id: uuid.UUID | None = None,
) -> None:
    """Create one durable in-app budget notice per camera/stage/day.

    This is deliberately best-effort: a notification write must never turn a
    budget decision into a failed perception call.  The stage is part of the
    dedupe key so a user sees both the early warning and the later block once.
    """
    from shared.database import async_session
    from shared.models import Notification

    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    marker = (
        "Rule AI budget warning:" if decision.stage == "warn" and rule_id else
        "Rule AI budget reached:" if rule_id else
        "Camera AI budget warning:" if decision.stage == "warn" else
        "Camera AI budget reached:"
    )
    try:
        async with async_session() as db:
            exists = await db.scalar(
                select(Notification.id).where(
                    Notification.camera_id == camera_id,
                    Notification.rule_id == rule_id,
                    Notification.created_at >= start,
                    Notification.message.startswith(marker),
                ).limit(1)
            )
            if exists:
                return
            notification = Notification(
                message=f"{marker} {decision.reason}",
                severity="warning",
                rule_id=rule_id,
                camera_id=camera_id,
            )
            db.add(notification)
            await db.commit()
            await db.refresh(notification)
            notification_id = str(notification.id)
        try:
            from services.api.ws import broadcast
            await broadcast({
                "type": "notification",
                "id": notification_id,
                "camera_id": str(camera_id),
                "message": notification.message,
                "severity": "warning",
            })
        except Exception:
            # The persisted row remains available after a reconnect.
            pass
    except Exception:
        # Budget enforcement is more important than its observability path.
        return


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
    actual_tokens_in: int | None = None,
    actual_tokens_out: int | None = None,
    actual_cost_cents: int | None = None,
) -> None:
    """Persist one best-effort usage row without affecting perception.

    Callers with provider-native usage counters should pass them so the ledger
    does not replace measured token counts with estimates. Cost remains the
    provider pricing estimate already used by the analyzer unless a caller
    supplies a native cost value.
    """
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
        native_tokens = actual_tokens_in is not None and actual_tokens_out is not None
        native_cost = actual_cost_cents is not None
        if native_tokens:
            tokens_in = max(0, int(actual_tokens_in))
            tokens_out = max(0, int(actual_tokens_out))
        if native_cost:
            cost_cents = max(0, int(actual_cost_cents))
        native_usage = native_tokens and native_cost
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
                # Token counts may be provider-native even when cost still
                # uses our pricing estimate because the provider does not
                # return a billable amount in its response.
                estimated=not native_usage,
                succeeded=succeeded,
            ))
            await db.commit()
    except Exception:
        # A usage ledger must never turn a camera alert into a failed alert.
        return
