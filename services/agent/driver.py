"""Agentic Q&A driver. Tool-use loop, budget enforcement, WS streaming.

The driver runs as a fire-and-forget asyncio task spawned by the
``POST /api/agent/ask`` route. It pushes structured events to
:func:`services.agent.ws.publish_event` for the per-run WS channel and
writes audit rows via :mod:`services.agent.runs`.

Failure modes (docs/agent-design.md section 13) are implemented as
guards inline. Each guard short-circuits with an event the frontend can
render rather than raising.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import jsonschema

from services.agent import runs as runs_mod
from services.agent.budget import check_budget, estimate_cost, record_usage
from services.agent.llm import LLMResponse, LLMToolUse, llm_call
from services.agent.tools import TOOL_REGISTRY, all_tools_for_provider, get_tool
from shared.app_settings import get_setting
from shared.database import async_session
from shared.models import AgentRun, Provider, User

logger = logging.getLogger("nurby.agent.driver")


# ── System prompt ────────────────────────────────────────────────────


SYSTEM_PROMPT_TEMPLATE = """You are Nurby Agent. You answer questions about a household's camera + audio data.

Workflow.
- Plan briefly inside <plan> tags before any tool calls.
- Use query_observations FIRST for any question about past activity. The indexed data answers most questions cheaply.
- Use analyze_clip or analyze_frame ONLY when indexed data does not answer the question. These are expensive.
- Use get_camera_layout when you need to know which cameras exist or what roles they have.
- Use get_journeys for "where did X go" or "when was X here" questions.

Citations.
- Cite every load-bearing claim by observation_id, journey_id, or vlm_call_id.
- Inline citation format. [obs:<uuid>] or [journey:<uuid>] or [vlm:<uuid>].

Honesty.
- If evidence is weak, say so. Hedge with "I think" or "possibly" below confidence 0.6.
- Never invent details. If a clip does not show what was asked, say it does not show.
- If the user asks something out-of-scope (weather, news, write actions, system config), politely decline.

Identity disambiguation.
- If a name matches multiple Persons, pick the one with the most recent activity OR ask the user.
- Never silently pick between equally-scored candidates.

Grounding.
- Current time. {now_iso}
- Household timezone. {system_timezone}
- Treat "today" / "yesterday" / "last night" relative to that timezone.

When you have enough evidence, write your final answer as plain prose. Do not call any more tools."""


# ── WS event bus integration ─────────────────────────────────────────


BroadcastFn = Callable[[str, dict], Awaitable[None]]


# ── Loop limits ──────────────────────────────────────────────────────


DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_VLM_CALLS = 8
DEFAULT_MAX_TOKENS_PER_CALL = 2048
DEDUPE_LOOKBACK_TURNS = 2
PARENT_CONTEXT_MAX_DEPTH = 3  # cap ancestor walk for conversation memory


@dataclass
class _LoopState:
    turn_index: int = 0
    tool_call_history: deque = field(default_factory=lambda: deque(maxlen=64))
    seq: int = 0
    vlm_calls_made: int = 0
    started_at: float = field(default_factory=time.time)


# ── Helpers ──────────────────────────────────────────────────────────


def _args_hash(name: str, args: dict) -> str:
    payload = json.dumps({"n": name, "a": args}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _arguments_summary(name: str, args: dict) -> str:
    """One-line human render of a tool call's arguments."""
    bits: list[str] = []
    for k, v in (args or {}).items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        bits.append(f"{k}={s}")
    body = " ".join(bits) if bits else "(no args)"
    return f"{name}({body})"


def _result_summary(name: str, result: dict) -> str:
    """One-line human render of a tool result."""
    if not isinstance(result, dict):
        return f"{name} -> {str(result)[:120]}"
    if "error" in result:
        return f"{name} -> error: {result.get('error')}"
    # cheap heuristics keyed off known tool shapes.
    if "observations" in result:
        n = result.get("count") or len(result.get("observations") or [])
        return f"{n} observations"
    if "journeys" in result:
        return f"{len(result['journeys'])} journeys"
    if "cameras" in result:
        return f"{len(result['cameras'])} cameras"
    if "answer" in result:
        ans = result.get("answer") or ""
        conf = result.get("confidence")
        return f"answer={str(ans)[:80]!r} confidence={conf}"
    # generic
    keys = ", ".join(sorted(list(result.keys()))[:6])
    return f"{name} -> {{{keys}}}"


# ── Conversation memory ─────────────────────────────────────────────


async def _load_parent_chain(parent_run_id: uuid.UUID, db) -> list[dict]:
    """Walk up to PARENT_CONTEXT_MAX_DEPTH ancestors and return canonical
    Anthropic-style messages summarizing prior turns. Newest last."""
    out: list[dict] = []
    cur = parent_run_id
    depth = 0
    chain: list[AgentRun] = []
    while cur and depth < PARENT_CONTEXT_MAX_DEPTH:
        run = await db.get(AgentRun, cur)
        if run is None:
            break
        chain.append(run)
        cur = run.parent_run_id
        depth += 1
    for run in reversed(chain):
        out.append({"role": "user", "content": run.question})
        if run.final_answer:
            out.append({"role": "assistant", "content": run.final_answer})
    return out


# ── Driver class ─────────────────────────────────────────────────────


class AgentDriver:
    """One-shot tool-use orchestrator for a single AgentRun."""

    def __init__(self, db_factory: Callable[[], Any] = async_session, broadcast: BroadcastFn | None = None):
        # ``db_factory`` is a callable that returns an async-context manager
        # yielding an AsyncSession. Tests inject a stub; production passes
        # the global ``async_session``.
        self.db_factory = db_factory
        self.broadcast = broadcast
        self._stop_event = asyncio.Event()

    async def stop(self) -> None:
        self._stop_event.set()

    # ── event emission ─────────────────────────────────────────────

    async def _emit(self, state: _LoopState, run_id: uuid.UUID, evt: dict) -> None:
        state.seq += 1
        payload = dict(evt)
        payload.setdefault("type", "unknown")
        payload["seq"] = state.seq
        payload["run_id"] = str(run_id)
        payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
        if self.broadcast is not None:
            try:
                await self.broadcast(str(run_id), payload)
            except Exception:
                logger.exception("broadcast failed for run %s", run_id)

    # ── public entry point ────────────────────────────────────────

    async def run(
        self,
        run_id: uuid.UUID,
        user: User,
        question: str,
        provider: Provider,
        model: str,
        parent_run_id: uuid.UUID | None,
    ) -> None:
        """Execute the tool-use loop for ``run_id`` to completion."""
        state = _LoopState()
        max_turns = int(await get_setting("agent_max_turns_per_run") or DEFAULT_MAX_TURNS)
        max_vlm = int(await get_setting("agent_max_vlm_calls_per_run") or DEFAULT_MAX_VLM_CALLS)
        system_tz = await get_setting("system_timezone") or "UTC"

        async with self.db_factory() as db:
            try:
                await self._emit(state, run_id, {
                    "type": "started",
                    "provider": provider.kind,
                    "model": model,
                })

                budget = await check_budget(user.id, db)
                if not budget.ok:
                    await self._emit(state, run_id, {
                        "type": "error",
                        "message": f"budget exhausted before start: {budget.reason}",
                        "recoverable": False,
                    })
                    await runs_mod.update_run(run_id, db, status="budget_exhausted",
                                              error_message=budget.reason,
                                              ended_at=datetime.now(timezone.utc))
                    return
                if budget.warn:
                    await self._emit(state, run_id, {
                        "type": "budget_warn",
                        "percent_used": int(max(
                            (budget.used_tokens * 100 / budget.token_budget) if budget.token_budget else 0,
                            (budget.used_cost_cents * 100 / budget.cost_budget_cents) if budget.cost_budget_cents else 0,
                        )),
                        "remaining_cents": budget.remaining_cost_cents,
                    })

                system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                    now_iso=datetime.now(timezone.utc).isoformat(),
                    system_timezone=system_tz,
                )

                messages: list[dict] = []
                if parent_run_id is not None:
                    messages.extend(await _load_parent_chain(parent_run_id, db))
                messages.append({"role": "user", "content": question})

                tools = all_tools_for_provider(provider.kind)

                final_text = ""
                forced = False

                while state.turn_index < max_turns:
                    if self._stop_event.is_set():
                        await self._emit(state, run_id, {"type": "cancelled", "reason": "user_cancelled"})
                        await runs_mod.cancel_run(run_id, "user_cancelled", db)
                        return

                    streamed_text_parts: list[str] = []

                    async def _on_token(delta: str) -> None:
                        streamed_text_parts.append(delta)
                        await self._emit(state, run_id, {"type": "synthesis_token", "delta": delta})

                    response: LLMResponse = await llm_call(
                        provider=provider,
                        model=model,
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=DEFAULT_MAX_TOKENS_PER_CALL,
                        stream=True,
                        stream_callback=_on_token,
                    )

                    # cost accounting + per-run rollup
                    call_cost = estimate_cost(provider.kind, model, response.tokens_in, response.tokens_out)
                    await record_usage(user.id, response.tokens_in, response.tokens_out, call_cost, db,
                                       increment_run_count=(state.turn_index == 0))
                    run_row = await runs_mod.update_run(
                        run_id, db,
                        tokens_in=(await self._cur_tokens(db, run_id, "in")) + response.tokens_in,
                        tokens_out=(await self._cur_tokens(db, run_id, "out")) + response.tokens_out,
                        cost_cents=(await self._cur_tokens(db, run_id, "cost")) + call_cost,
                        turns_used=state.turn_index + 1,
                    )

                    post_budget = await check_budget(user.id, db)
                    if not post_budget.ok:
                        # forced synthesis from what we know
                        await self._emit(state, run_id, {"type": "budget_warn",
                                                          "percent_used": 100,
                                                          "remaining_cents": 0})
                        final_text = await self._forced_synthesis(provider, model, system_prompt, messages, state, run_id)
                        await runs_mod.update_run(run_id, db,
                                                  status="budget_exhausted",
                                                  final_answer=final_text,
                                                  ended_at=datetime.now(timezone.utc))
                        await self._emit_done(state, run_id, final_text, run_row, partial=True)
                        return

                    # text or end_turn => final answer.
                    if response.stop_reason in {"end_turn", "stop"} or not response.tool_uses:
                        final_text = response.text or "".join(streamed_text_parts)
                        await runs_mod.update_run(run_id, db,
                                                  status="completed",
                                                  final_answer=final_text,
                                                  ended_at=datetime.now(timezone.utc),
                                                  latency_ms=int((time.time() - state.started_at) * 1000))
                        await self._emit_done(state, run_id, final_text, run_row, partial=False)
                        return

                    # assistant message with tool_use blocks
                    asst_blocks: list[dict] = []
                    if response.text:
                        asst_blocks.append({"type": "text", "text": response.text})
                    for tu in response.tool_uses:
                        asst_blocks.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.arguments})
                    messages.append({"role": "assistant", "content": asst_blocks})

                    # execute each tool use, append tool_result blocks
                    tool_result_blocks: list[dict] = []
                    for tu in response.tool_uses:
                        result = await self._exec_tool(tu, state, run_id, user, db, max_vlm)
                        tool_result_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "tool_name": tu.name,
                            "content": json.dumps(result)[:8000],
                        })
                    messages.append({"role": "user", "content": tool_result_blocks})

                    state.turn_index += 1

                # max turns reached. forced synthesis.
                await self._emit(state, run_id, {"type": "error",
                                                  "message": "max_turns_reached",
                                                  "recoverable": False})
                final_text = await self._forced_synthesis(provider, model, system_prompt, messages, state, run_id)
                run_row = await runs_mod.update_run(run_id, db,
                                                   status="completed",
                                                   final_answer=final_text,
                                                   ended_at=datetime.now(timezone.utc),
                                                   latency_ms=int((time.time() - state.started_at) * 1000))
                await self._emit_done(state, run_id, final_text, run_row, partial=True)
            except Exception as exc:
                logger.exception("agent driver failed run=%s", run_id)
                await self._emit(state, run_id, {"type": "error",
                                                  "message": f"{type(exc).__name__}: {exc}",
                                                  "recoverable": False})
                try:
                    await runs_mod.update_run(run_id, db, status="failed",
                                              error_message=str(exc),
                                              ended_at=datetime.now(timezone.utc))
                except Exception:
                    logger.debug("failed to mark run failed", exc_info=True)

    # ── tool execution ────────────────────────────────────────────

    async def _exec_tool(
        self,
        tu: LLMToolUse,
        state: _LoopState,
        run_id: uuid.UUID,
        user: User,
        db,
        max_vlm: int,
    ) -> dict:
        name = tu.name
        args = tu.arguments or {}
        h = _args_hash(name, args)

        # dedupe within last DEDUPE_LOOKBACK_TURNS
        recent = [e for e in state.tool_call_history if e["turn"] >= state.turn_index - DEDUPE_LOOKBACK_TURNS]
        if any(e["hash"] == h for e in recent):
            await self._emit(state, run_id, {
                "type": "tool_result",
                "call_id": tu.id,
                "name": name,
                "result_summary": "tool_loop_detected. skipping duplicate call.",
                "latency_ms": 0,
            })
            return {"error": "tool_loop_detected",
                    "message": "you already called this tool with these args; pick a different approach or finish"}

        tool = get_tool(name)
        if tool is None:
            await self._emit(state, run_id, {"type": "tool_result", "call_id": tu.id, "name": name,
                                              "result_summary": "unknown tool", "latency_ms": 0})
            return {"error": "unknown_tool", "message": f"no tool named {name!r}"}

        # validate arguments against schema
        try:
            jsonschema.validate(instance=args, schema=tool["input_schema"])
        except jsonschema.ValidationError as ve:
            await self._emit(state, run_id, {"type": "tool_result", "call_id": tu.id, "name": name,
                                              "result_summary": f"invalid args: {ve.message}", "latency_ms": 0})
            return {"error": "invalid_arguments", "message": ve.message}

        # VLM cap check
        if name in {"analyze_clip", "analyze_frame"}:
            if state.vlm_calls_made >= max_vlm:
                await self._emit(state, run_id, {"type": "tool_result", "call_id": tu.id, "name": name,
                                                  "result_summary": "vlm cap reached", "latency_ms": 0})
                return {"error": "vlm_cap_reached", "message": f"agent_max_vlm_calls_per_run={max_vlm}"}
            state.vlm_calls_made += 1

        # emit tool_start
        await self._emit(state, run_id, {
            "type": "tool_start",
            "call_id": tu.id,
            "name": name,
            "arguments_summary": _arguments_summary(name, args),
        })

        # persist tool call row + execute
        call_row = await runs_mod.append_tool_call(run_id, state.turn_index, name, args, db)
        t0 = time.time()
        try:
            ctx = {"user": user, "run_id": run_id, "db": db}
            result = await tool["fn"](ctx, **args)
        except Exception as exc:
            result = {"error": "tool_exception", "message": f"{type(exc).__name__}: {exc}"}
            logger.exception("tool %s raised", name)
        latency_ms = int((time.time() - t0) * 1000)
        try:
            await runs_mod.complete_tool_call(call_row.id, db,
                                              result=result if isinstance(result, dict) else {"value": result},
                                              error=result.get("error") if isinstance(result, dict) else None,
                                              latency_ms=latency_ms)
        except Exception:
            logger.debug("complete_tool_call failed", exc_info=True)

        state.tool_call_history.append({"turn": state.turn_index, "hash": h, "name": name})

        await self._emit(state, run_id, {
            "type": "tool_result",
            "call_id": tu.id,
            "name": name,
            "result_summary": _result_summary(name, result if isinstance(result, dict) else {"value": result}),
            "cached": bool(result.get("cached")) if isinstance(result, dict) else False,
            "latency_ms": latency_ms,
        })
        return result if isinstance(result, dict) else {"value": result}

    # ── forced synthesis ──────────────────────────────────────────

    async def _forced_synthesis(self, provider, model, system_prompt, messages, state, run_id) -> str:
        """One final non-tool LLM call asking for a partial summary."""
        prompt = system_prompt + "\n\nIMPORTANT. You are out of budget or turns. Summarize what you know from the evidence gathered so far. Do not call any more tools."
        try:
            resp = await llm_call(
                provider=provider,
                model=model,
                system_prompt=prompt,
                messages=messages + [{"role": "user",
                                       "content": "Please give a partial answer based on the evidence gathered so far. Make clear you ran out of time."}],
                tools=[],
                max_tokens=DEFAULT_MAX_TOKENS_PER_CALL,
                stream=False,
            )
            text = resp.text or "(no answer produced; investigation halted before synthesis)"
        except Exception as exc:
            logger.exception("forced synthesis failed")
            text = f"(investigation halted: {exc})"
        await self._emit(state, run_id, {"type": "synthesis_token", "delta": text})
        return text

    # ── done emission ─────────────────────────────────────────────

    async def _emit_done(self, state, run_id, final_text, run_row, *, partial: bool) -> None:
        await self._emit(state, run_id, {
            "type": "done",
            "final_answer": final_text,
            "citations": _extract_citations(final_text),
            "total_cost_cents": getattr(run_row, "cost_cents", 0),
            "total_tokens": getattr(run_row, "tokens_in", 0) + getattr(run_row, "tokens_out", 0),
            "turns": getattr(run_row, "turns_used", state.turn_index),
            "partial": partial,
        })

    # ── token rollup helper ───────────────────────────────────────

    async def _cur_tokens(self, db, run_id: uuid.UUID, which: str) -> int:
        row = await db.get(AgentRun, run_id)
        if row is None:
            return 0
        if which == "in":
            return int(row.tokens_in or 0)
        if which == "out":
            return int(row.tokens_out or 0)
        if which == "cost":
            return int(row.cost_cents or 0)
        return 0


# ── Citation extractor ───────────────────────────────────────────────


import re as _re

_CIT_RE = _re.compile(r"\[(obs|journey|vlm|recording):([0-9a-fA-F-]{36})\]")


def _extract_citations(text: str) -> list[dict]:
    out: list[dict] = []
    for m in _CIT_RE.finditer(text or ""):
        out.append({"kind": m.group(1), "id": m.group(2)})
    return out


__all__ = [
    "AgentDriver",
    "SYSTEM_PROMPT_TEMPLATE",
    "DEFAULT_MAX_TURNS",
    "DEFAULT_MAX_VLM_CALLS",
    "PARENT_CONTEXT_MAX_DEPTH",
]
