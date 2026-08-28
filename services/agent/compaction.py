"""Keep the conversation from growing without bound (issue #135).

The driver appended to ``messages`` monotonically for up to twelve turns
and never compacted. With tool results capped at 8k each plus the
household block, a long run sends a very large prompt every turn, and the
whole history is re-sent each time, so input token cost grows
quadratically in turns. On a household running a local model with a small
context window the run does not degrade, it overflows.

This is the cheap half of the fix, and it is deliberately not an LLM
call: tool results older than the last couple of turns are replaced by
the one-line summary the driver already computes for its WS events. No
model, no latency, no cost, and it removes most of the growth.

Two things are preserved on purpose.

**Citable ids.** A condensed result keeps a handful of the uuids it
contained. The driver strips citations pointing at ids no tool returned,
so an answer citing evidence the model can no longer see would have its
support deleted and be left as a bare claim. Condensing must not quietly
destroy the ability to cite what was found five turns ago.

**The fact that it was condensed.** The replacement says so, so the model
treats it as a summary of a result rather than as the result.

Everything here is pure. The driver owns the message list; this decides
what a shorter version of it looks like.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("nurby.agent.compaction")

# Turns whose tool results stay verbatim. Two is enough for the model to
# still be working with the rows it just asked for, which is when it
# needs the detail.
DEFAULT_KEEP_RECENT_TURNS = 2

# Ids carried through a condensed result. Enough to cite the evidence
# that mattered, not so many that the "summary" is a list of uuids.
MAX_IDS_KEPT = 5

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

CONDENSED_PREFIX = "[condensed]"


def is_tool_result_message(message: dict) -> bool:
    """Whether a message carries tool results. Pure, for tests."""
    content = (message or {}).get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def condense_block(block: dict, summarize) -> dict:
    """One tool_result block, shortened to its summary plus its ids.

    ``summarize`` is ``(tool_name, parsed_result) -> str``; the driver
    passes the same function it uses for its WS events, so the model and
    the user see the same description of what a call returned. Pure.
    """
    raw = block.get("content")
    if not isinstance(raw, str) or raw.startswith(CONDENSED_PREFIX):
        return block

    name = block.get("tool_name") or "tool"
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        try:
            summary = summarize(name, parsed)
        except Exception:  # noqa: BLE001 - a summary must never break a run
            logger.debug("summarize failed for %s", name, exc_info=True)
            summary = name
    else:
        summary = name

    ids = []
    for match in _UUID_RE.finditer(raw):
        value = match.group(0)
        if value not in ids:
            ids.append(value)
        if len(ids) >= MAX_IDS_KEPT:
            break

    text = f"{CONDENSED_PREFIX} {summary}"
    if ids:
        # Kept so a later turn can still cite this evidence. Without them
        # the driver's citation check would strip the citation and leave
        # the claim standing with nothing behind it.
        text += " | ids: " + ", ".join(ids)

    out = dict(block)
    out["content"] = text
    return out


def compact_messages(
    messages: list[dict],
    summarize,
    keep_recent_turns: int = DEFAULT_KEEP_RECENT_TURNS,
) -> tuple[list[dict], int]:
    """Condense tool results older than the last ``keep_recent_turns``.

    Returns the new message list and how many blocks were condensed. The
    input is not mutated. Pure, for tests.
    """
    indices = [i for i, m in enumerate(messages) if is_tool_result_message(m)]
    if len(indices) <= keep_recent_turns:
        return list(messages), 0

    stale = set(indices[: len(indices) - keep_recent_turns] if keep_recent_turns
                else indices)
    out: list[dict] = []
    condensed = 0
    for i, message in enumerate(messages):
        if i not in stale:
            out.append(message)
            continue
        blocks = []
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                new_block = condense_block(block, summarize)
                if new_block is not block:
                    condensed += 1
                blocks.append(new_block)
            else:
                blocks.append(block)
        new_message = dict(message)
        new_message["content"] = blocks
        out.append(new_message)
    return out, condensed


def approximate_size(messages: list[dict]) -> int:
    """Serialized character count of a message list. Pure, for tests."""
    try:
        return len(json.dumps(messages, default=str))
    except (TypeError, ValueError):
        return sum(len(str(m)) for m in messages)
