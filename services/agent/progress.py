"""Notice when a run is going nowhere (issue #138).

The loop guard hashed ``{name, args}`` with SHA-256 and rejected an exact
repeat within two turns. It caught literal repetition and nothing else:
``hours=24`` followed by ``hours=25`` is a different hash, and an
A, B, A, B alternation never repeats inside a two-turn window.

Worse, the loop had no notion of **progress**. A run could burn all
twelve turns making distinct, valid, entirely uninformative calls, and
nothing noticed until the turn cap fired.

Two ideas here.

**Normalized signatures.** Numeric arguments are bucketed before hashing,
so calls that differ only in noise collide. The window ladder is
preserved deliberately: the system prompt tells the model to escalate
24 -> 168 -> 720 hours when a query comes back empty, and a guard that
collapsed those into one signature would block the widening strategy the
prompt depends on. So hours round to the nearest ladder rung, which makes
24 and 25 the same call while keeping 24 and 168 different.

**A progress metric.** The driver already accumulates every uuid any tool
returned, for the citation check. Growth of that set is a direct measure
of whether a turn learned anything, and it catches semantic spinning that
argument hashing structurally cannot.

A turn also counts as progress when it calls a tool for the first time,
because several useful tools return no ids at all (the camera layout, the
rule list, the doctor). Judging those as "no progress" would nag a run
that is doing exactly the right thing.
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger("nurby.agent.progress")

# Consecutive turns without progress before the model is told. One is
# noise: a turn can legitimately confirm an absence.
NUDGE_AFTER_TURNS = 2

# Consecutive turns without progress before the run is cut short and
# synthesized from what it has. Spending the remaining turns the same way
# only costs money.
HALT_AFTER_TURNS = 3

# Window ladder from the system prompt's widen-then-fail rule. Kept in
# sync with tools.widen_ladder: values round to the nearest rung so noise
# collides while a genuine escalation stays a distinct call.
WINDOW_RUNGS = (1, 24, 168, 720)

# Arguments whose value is a time window in hours.
_WINDOW_KEYS = {"hours", "window_hours", "lookback_hours"}


def _nearest_rung(value: float) -> int:
    return min(WINDOW_RUNGS, key=lambda rung: abs(rung - value))


def _bucket(key: str, value):
    """One argument value, coarsened so noise collides. Pure."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        if key in _WINDOW_KEYS:
            return _nearest_rung(float(value))
        # One significant figure. limit=20 and limit=21 are the same
        # query and should collide; limit=20 and limit=100 are not.
        # Deliberately coarse: this feeds a loop guard, where a false
        # collision costs one blocked duplicate call and a missed one
        # costs a wasted turn.
        if value == 0:
            return 0
        magnitude = abs(value)
        digits = len(str(int(magnitude)))
        step = max(1, 10 ** (digits - 1))
        return int(round(value / step) * step)
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return [_bucket(key, v) for v in value]
    if isinstance(value, dict):
        return {k: _bucket(k, v) for k, v in sorted(value.items())}
    return value


def normalize_args(args: dict | None) -> dict:
    """Arguments with numeric noise removed. Pure, for tests."""
    return {k: _bucket(k, v) for k, v in sorted((args or {}).items())}


def call_signature(name: str, args: dict | None) -> str:
    """A hash that treats near-identical calls as the same call. Pure."""
    payload = json.dumps(
        {"n": name, "a": normalize_args(args)}, sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def made_progress(
    ids_before: int, ids_after: int, tools_called: set[str], tools_seen: set[str]
) -> bool:
    """Whether a turn learned anything. Pure, for tests.

    New evidence counts. So does calling a tool for the first time, since
    several tools return no ids at all and a run reaching for one of them
    is doing the right thing, not spinning.
    """
    if ids_after > ids_before:
        return True
    return bool(tools_called - tools_seen)


def verdict(zero_gain_turns: int) -> str:
    """``ok`` | ``nudge`` | ``halt`` for a run of empty turns. Pure."""
    if zero_gain_turns >= HALT_AFTER_TURNS:
        return "halt"
    if zero_gain_turns >= NUDGE_AFTER_TURNS:
        return "nudge"
    return "ok"


def nudge_text(zero_gain_turns: int) -> str:
    """What to tell a model that is not getting anywhere. Pure."""
    return (
        f"Your last {zero_gain_turns} turns returned no new evidence."
        " Either change approach (widen the time window, search a"
        " different way, or ask about a different entity), or answer now"
        " with what you already have, saying plainly what you could not"
        " find."
    )
