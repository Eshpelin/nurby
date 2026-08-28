"""Prompt caching and the thing that was busting it (issue #136).

grep -rn cache_control services/ returned nothing, so the Anthropic path
re-paid full input price for the system prompt, ~20 tool schemas, and the
whole accumulated history on every turn of every run. A 12-turn run paid
for the same prefix a dozen times.

Marking the prefix is half the fix. The other half is that the system
prompt carried a per-run ISO timestamp, so the first bytes of every
request differed and no two runs could ever share a cache entry.
"""

import re

from services.agent import driver as driver_mod
from services.agent.llm import apply_system_cache, apply_tools_cache


# ---- the breakpoints -----------------------------------------------------


def test_the_system_prompt_is_marked_cacheable():
    out = apply_system_cache("you are an agent")
    assert out == [{
        "type": "text",
        "text": "you are an agent",
        "cache_control": {"type": "ephemeral"},
    }]


def test_only_the_last_tool_is_marked():
    """A breakpoint caches everything up to and including itself, so one
    on the last tool covers the whole array."""
    tools = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    out = apply_tools_cache(tools)

    assert "cache_control" not in out[0]
    assert "cache_control" not in out[1]
    assert out[2]["cache_control"] == {"type": "ephemeral"}


def test_the_caller_s_tool_list_is_not_mutated():
    """The driver builds tools once and reuses the list every turn. A
    mutation here would compound a breakpoint onto it each time."""
    tools = [{"name": "a"}, {"name": "b"}]
    apply_tools_cache(tools)
    apply_tools_cache(tools)

    assert all("cache_control" not in t for t in tools)


def test_empty_inputs_are_left_alone():
    assert apply_tools_cache([]) == []
    assert apply_system_cache("") == ""


# ---- the cache buster ----------------------------------------------------


def test_the_system_prompt_carries_no_timestamp():
    """The regression this fixes. A per-run timestamp in the cached
    prefix means the prefix is never the same twice."""
    prompt = driver_mod.SYSTEM_PROMPT_TEMPLATE
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", prompt)
    # And no leftover format placeholders that would reintroduce one.
    assert "{now_iso}" not in prompt
    assert "{system_timezone}" not in prompt


def test_the_system_prompt_is_a_plain_string_now():
    """It is used directly rather than through .format(), so a brace in a
    camera or person name cannot break it either."""
    assert isinstance(driver_mod.SYSTEM_PROMPT_TEMPLATE, str)
    assert "{" not in driver_mod.SYSTEM_PROMPT_TEMPLATE


def test_grounding_moved_onto_the_question():
    grounded = driver_mod._ground_question("where is the cat?", "Asia/Dhaka")

    assert "Current time:" in grounded
    assert "Household timezone: Asia/Dhaka" in grounded
    assert grounded.endswith("where is the cat?")


def test_the_prompt_still_tells_the_model_where_to_look():
    """Moving the grounding is only safe if the instruction points at its
    new home."""
    assert "given with the question" in driver_mod.SYSTEM_PROMPT_TEMPLATE


def test_two_runs_share_an_identical_prefix():
    """The property that makes caching possible at all."""
    first = driver_mod.SYSTEM_PROMPT_TEMPLATE
    second = driver_mod.SYSTEM_PROMPT_TEMPLATE
    assert first == second

    # while the questions still differ by time
    a = driver_mod._ground_question("q", "UTC")
    b = driver_mod._ground_question("q", "UTC")
    assert a.split("\n")[0].startswith("Current time:")
    assert b.split("\n")[0].startswith("Current time:")


# ---- the request body ----------------------------------------------------


def test_the_anthropic_body_carries_both_breakpoints(monkeypatch):
    """End to end over the request builder: what actually goes on the
    wire has the markers."""
    import asyncio
    from types import SimpleNamespace

    import httpx

    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"content": [{"type": "text", "text": "hi"}],
                    "stop_reason": "end_turn", "usage": {}}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(json or {})
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    from services.agent.llm import _call_anthropic

    provider = SimpleNamespace(kind="anthropic", api_key="k", base_url=None,
                               reasoning_effort=None, reasoning_enabled=False)
    asyncio.run(_call_anthropic(
        provider, "claude-x", "system text", [{"role": "user", "content": "q"}],
        [{"name": "t1"}, {"name": "t2"}], 1024, False, None,
    ))

    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in captured["tools"][0]
