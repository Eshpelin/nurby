"""Which rule actions take a real-world action, for review-first defaults.

A "consequential" action does something outside Nurby that a person would
want to look at before it can fire on its own: it drives a physical device
or relay (``device``), speaks over a camera speaker (``speak``), or writes
into another system over HTTP (``api_call``, ``webhook``).

Informational actions (``notify``, ``telegram``, ``email``) and the in-app
``broadcast``, plus internal analysis steps (``verify``, ``locate``,
``vlm_call``), are NOT consequential: at worst they send a message or spend a
model call. There is no external side effect whose success a rule could
fabricate.

Rules that contain a consequential action are created review-first
(disabled) so a suspected entry cannot, by itself, charge a fee or trip a
barrier before a human has reviewed the evidence. See issue #192 and
``docs/product-review-2026-09-16.md``. A consequential action can also live
in a sequence's ``on_timeout`` list (the trigger pattern), so detection
looks there too, not only at the top-level action chain.
"""

from __future__ import annotations

from typing import Any

# Real-world side effects. Keep in sync with the action executors in
# services/events/actions.py that reach outside Nurby.
CONSEQUENTIAL_ACTION_TYPES: frozenset[str] = frozenset(
    {"api_call", "webhook", "device", "speak"}
)


def _as_action_list(actions: Any) -> list[dict]:
    """Normalize an action chain (a dict, a list, or None) to a list of dicts."""
    if actions is None:
        return []
    if isinstance(actions, dict):
        return [actions]
    if isinstance(actions, list):
        return [a for a in actions if isinstance(a, dict)]
    return []


def action_is_consequential(action: Any) -> bool:
    """True when a single action drives a real-world side effect."""
    return (
        isinstance(action, dict)
        and action.get("type") in CONSEQUENTIAL_ACTION_TYPES
    )


def _timeout_actions(trigger_pattern: Any) -> list[dict]:
    """Consequential actions can sit in a sequence's ``on_timeout`` list
    (e.g. the line-stoppage template opens a work order there). Pull those
    out so detection sees them even when the top-level chain is empty."""
    if not isinstance(trigger_pattern, dict):
        return []
    sequence = trigger_pattern.get("sequence")
    if not isinstance(sequence, dict):
        return []
    return _as_action_list(sequence.get("on_timeout"))


def rule_is_consequential(
    actions: Any, trigger_pattern: Any = None
) -> bool:
    """True when a rule contains any consequential action, in its action
    chain or in a sequence ``on_timeout`` block."""
    candidates = _as_action_list(actions) + _timeout_actions(trigger_pattern)
    return any(action_is_consequential(a) for a in candidates)
