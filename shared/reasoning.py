"""Optional per-provider reasoning / "thinking" model controls (issue #41).

Reasoning-capable models (Anthropic extended/adaptive thinking, OpenAI
o-series / gpt-5-class reasoning effort) emit internal reasoning tokens
that are NOT part of the user-facing answer but ARE billed as output
tokens. This module is the single place that:

1. Builds the provider-specific request fields from a ``Provider`` row,
   gated entirely off opt-in config so default behavior is unchanged.
2. Strips Anthropic ``thinking`` / ``redacted_thinking`` content blocks
   so reasoning text never leaks into captions or agent answers.
3. Surfaces the reasoning-token count from a provider response so the
   budget accounting can include it (don't undercount).

Everything reads config via ``getattr(provider, ..., None)`` so test
fakes (``SimpleNamespace``) and older Provider rows without the new
columns keep working — a missing attribute means "off".

Anthropic wire shape (authoritative, per the claude-api reference):
* Adaptive (Opus 4.6+ / Sonnet 4.6): ``thinking={"type": "adaptive"}``,
  optionally with ``output_config={"effort": ...}``. ``budget_tokens``
  is removed on Opus 4.7+/Fable and deprecated on 4.6.
* Fixed budget (older models only): ``thinking={"type": "enabled",
  "budget_tokens": N}`` where ``N`` must be < ``max_tokens`` and >= 1024.

OpenAI reasoning models take ``reasoning_effort`` ("minimal" | "low" |
"medium" | "high"). Non-reasoning chat models ignore it.
"""

from __future__ import annotations

from typing import Any

# Valid opt-in values. Anything else (including None) means "off".
_ANTHROPIC_MODES = {"adaptive", "enabled"}
_OPENAI_EFFORTS = {"minimal", "low", "medium", "high"}
# Anthropic's documented floor for a fixed thinking budget.
_MIN_THINKING_BUDGET = 1024


def anthropic_thinking_params(provider: Any, max_tokens: int | None) -> dict[str, Any]:
    """Return the Anthropic request fields to merge for thinking, or {}.

    ``max_tokens`` is the resolved output cap for this call; it bounds a
    fixed ``budget_tokens`` so the request never 400s on
    ``budget_tokens >= max_tokens``. Returns an empty dict when thinking
    is off (the default), so the call body is byte-identical to before.
    """
    mode = (getattr(provider, "anthropic_thinking", None) or "").strip().lower()
    if mode not in _ANTHROPIC_MODES:
        return {}

    if mode == "adaptive":
        return {"thinking": {"type": "adaptive"}}

    # mode == "enabled": fixed budget for older models.
    budget = getattr(provider, "anthropic_thinking_budget_tokens", None)
    try:
        budget = int(budget) if budget is not None else None
    except (TypeError, ValueError):
        budget = None
    if budget is None or budget < _MIN_THINKING_BUDGET:
        budget = _MIN_THINKING_BUDGET
    # budget_tokens must be strictly less than max_tokens. If the output
    # cap can't house the budget plus room for an answer, fall back to
    # adaptive rather than emitting an invalid request.
    if max_tokens is not None and budget >= max_tokens:
        if max_tokens > _MIN_THINKING_BUDGET + 256:
            budget = max_tokens - 256
        else:
            return {"thinking": {"type": "adaptive"}}
    return {"thinking": {"type": "enabled", "budget_tokens": budget}}


def openai_reasoning_params(provider: Any) -> dict[str, Any]:
    """Return the OpenAI request fields to merge for reasoning, or {}.

    Off by default. When set, emits ``reasoning_effort``; harmlessly
    ignored by non-reasoning chat models on the OpenAI-compatible API.
    """
    effort = (getattr(provider, "openai_reasoning_effort", None) or "").strip().lower()
    if effort not in _OPENAI_EFFORTS:
        return {}
    return {"reasoning_effort": effort}


def anthropic_visible_text(content_blocks: list[dict] | None) -> str:
    """Join only the user-visible ``text`` blocks from an Anthropic response.

    ``thinking`` and ``redacted_thinking`` blocks are dropped so reasoning
    never reaches a caption or agent answer. Safe on responses with no
    thinking blocks (the normal, thinking-off case).
    """
    if not content_blocks:
        return ""
    parts: list[str] = []
    for blk in content_blocks:
        if isinstance(blk, dict) and blk.get("type") == "text":
            parts.append(blk.get("text") or "")
    return "".join(parts)


def is_thinking_block(block_type: str | None) -> bool:
    """True for Anthropic content-block types that carry reasoning, not answer."""
    return block_type in {"thinking", "redacted_thinking"}


def openai_reasoning_tokens(usage: dict | None) -> int:
    """Reasoning tokens reported by an OpenAI response, or 0.

    OpenAI nests these under
    ``usage.completion_tokens_details.reasoning_tokens``. They are
    already included in ``completion_tokens`` — this helper exists for
    observability and to assert no undercount, NOT to be added on top of
    ``completion_tokens`` (that would double-count).
    """
    if not usage:
        return 0
    details = usage.get("completion_tokens_details") or {}
    try:
        return int(details.get("reasoning_tokens") or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "anthropic_thinking_params",
    "openai_reasoning_params",
    "anthropic_visible_text",
    "is_thinking_block",
    "openai_reasoning_tokens",
]
