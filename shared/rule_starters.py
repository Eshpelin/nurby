"""Starter alert rules, as data, for the first-run flow.

The web app has 23 rule templates, but they are TypeScript functions that
build a rule from context, so they cannot be shared. Mobile therefore had
no templates at all and a new household's only path to its first alert
was the rule builder.

These five are the ones worth having in the first ten minutes. They are
plain data rather than builders: a camera id is the only thing they need
filled in, and `notify` works without Telegram or email configured, so
one tap produces a rule that actually fires. Everything else stays in the
web template library.

Served by GET /api/rules/starters.
"""

from __future__ import annotations

from typing import Any

STARTERS: list[dict[str, Any]] = [
    {
        "key": "someone-at-the-door",
        "title": "Tell me when someone is at the door",
        "blurb": "A person is seen, and you get a notification.",
        "icon": "person",
        "needs_camera": True,
        "rule": {
            "name": "Someone at the door",
            "enabled": True,
            "trigger_pattern": {"type": "object_detected", "label": "person"},
            "conditions": None,
            "actions": [
                {
                    "type": "notify",
                    "message": "Someone is at {camera_name}",
                    "include_thumbnail": True,
                }
            ],
            "cooldown_seconds": 300,
            "severity": "info",
        },
    },
    {
        # The Home/Away use case (#184) as a one-tap rule. Deliberately a
        # separate starter from "someone at the door" rather than a mode
        # gate on it: the plain version is the first alert a new household
        # sees, and it has to fire while they are standing there testing it.
        "key": "someone-at-the-door-while-out",
        "title": "Tell me about people at the door only while we're out",
        "blurb": "Quiet while someone is home. Armed the moment you set the house to Away or Night.",
        "icon": "person",
        "needs_camera": True,
        "rule": {
            "name": "Someone at the door while we're out",
            "enabled": True,
            "trigger_pattern": {"type": "object_detected", "label": "person"},
            "conditions": {"modes": ["away", "night"]},
            "actions": [
                {
                    "type": "notify",
                    "message": "Someone is at {camera_name} and nobody is home",
                    "include_thumbnail": True,
                }
            ],
            "cooldown_seconds": 300,
            "severity": "alert",
        },
    },
    {
        "key": "package-arrived",
        "title": "Tell me when a package arrives",
        "blurb": "A package is seen near a camera.",
        "icon": "package",
        "needs_camera": True,
        "rule": {
            "name": "Package arrived",
            "enabled": True,
            "trigger_pattern": {"type": "object_detected", "label": "package"},
            "conditions": None,
            "actions": [
                {
                    "type": "notify",
                    "message": "A package arrived at {camera_name}",
                    "include_thumbnail": True,
                }
            ],
            "cooldown_seconds": 600,
            "severity": "info",
        },
    },
    {
        "key": "car-in-the-drive",
        "title": "Tell me when a car pulls in",
        "blurb": "A vehicle is seen on a chosen camera.",
        "icon": "car",
        "needs_camera": True,
        "rule": {
            "name": "Car in the drive",
            "enabled": True,
            "trigger_pattern": {"type": "object_detected", "label": "car"},
            "conditions": None,
            "actions": [
                {
                    "type": "notify",
                    "message": "A car pulled in at {camera_name}",
                    "include_thumbnail": True,
                }
            ],
            "cooldown_seconds": 600,
            "severity": "info",
        },
    },
    {
        "key": "someone-at-night",
        "title": "Tell me about anyone after dark",
        "blurb": "A person is seen between 10pm and 6am.",
        "icon": "moon",
        "needs_camera": True,
        "rule": {
            "name": "Someone after dark",
            "enabled": True,
            "trigger_pattern": {"type": "object_detected", "label": "person"},
            "conditions": {"time_range": {"start": "22:00", "end": "06:00"}},
            "actions": [
                {
                    "type": "notify",
                    "message": "Someone is at {camera_name} after dark",
                    "include_thumbnail": True,
                }
            ],
            "cooldown_seconds": 300,
            "severity": "warning",
        },
    },
]


def starter_rule(key: str, camera_id: str | None) -> dict[str, Any] | None:
    """The rule body for a starter, scoped to one camera. Pure.

    Returns None for an unknown key rather than a half-built rule: a
    silently empty trigger would create a rule that never fires and look
    like it worked.
    """
    for s in STARTERS:
        if s["key"] != key:
            continue
        rule = {k: (dict(v) if isinstance(v, dict) else v) for k, v in s["rule"].items()}
        rule["actions"] = [dict(a) for a in s["rule"]["actions"]]
        if camera_id:
            trigger = dict(rule["trigger_pattern"])
            trigger["camera_id"] = camera_id
            rule["trigger_pattern"] = trigger
        return rule
    return None
