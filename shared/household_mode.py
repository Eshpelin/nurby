"""Household mode: is anyone home?

One value for the whole household, ``home``, ``away`` or ``night``. Rules
opt in to a subset of modes through ``conditions.modes``; a rule with no
``modes`` fires in every mode, which is what every rule written before
this existed does.

The mode is a setting (``household_mode`` in app settings) plus a history
table, so the timeline can show when it changed and who changed it. The
setting is the thing the rule engine reads once per tick; the history is
for people.

Kept free of SQLAlchemy so the engine, the API, the agent tools and the
starter rules can all import it without pulling the ORM.
"""

from __future__ import annotations

MODES: tuple[str, ...] = ("home", "away", "night")
DEFAULT_MODE = "home"

# UI wording, kept beside the values so the three clients agree.
MODE_LABELS: dict[str, str] = {
    "home": "Home",
    "away": "Away",
    "night": "Night",
}

# One line each, for a control that shows what the mode means.
MODE_HINTS: dict[str, str] = {
    "home": "Rules for when someone is in. Door alerts stay quiet.",
    "away": "Nobody home. Every rule armed.",
    "night": "Everyone in for the night. Outdoor rules armed, indoor quiet.",
}

# How a mode came to be set. ``manual`` is a person tapping a control;
# ``agent`` is the Ask agent acting on an instruction; ``auto`` is left
# for a presence detector that does not exist yet.
SOURCES: tuple[str, ...] = ("manual", "agent", "auto")


def is_mode(value: object) -> bool:
    return isinstance(value, str) and value in MODES


def rule_active_in(conditions: dict | None, mode: str) -> bool:
    """Whether a rule with these conditions fires while the household is
    in ``mode``. No ``modes`` key, or an empty one, means always."""
    modes = (conditions or {}).get("modes")
    if not modes:
        return True
    return mode in modes


def normalize_modes(value: object) -> list[str] | None:
    """Coerce a ``conditions.modes`` value to a clean list, or ``None`` if
    it should be treated as absent. Unknown modes are dropped rather than
    rejected so a rule written against a future mode does not fail to load."""
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return None
    out = [m for m in dict.fromkeys(str(v).strip().lower() for v in value) if m in MODES]
    return out or None
