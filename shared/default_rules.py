"""The product-default rules Nurby installs lazily.

Rules are household data, so migrations cannot own them: both the API
(services/api/routes/rules.py) and the rule engine
(services/events/engine.py) install the camera content-health pair the
first time they touch the rules table. This module is the single source
of truth for their names, triggers, and message templates.

Legacy message templates are kept here so an install that already carries
the pre-#320 wording gets it rewritten in place by the same ensure path.
The originals rendered as "the camera camera health degraded: [reason]"
in every preview surface.
"""

CAMERA_HEALTH_RULE_NAME = "Camera content health"
CAMERA_RECOVERY_RULE_NAME = "Camera content health recovered"

DEFAULT_RULE_NAMES = (CAMERA_HEALTH_RULE_NAME, CAMERA_RECOVERY_RULE_NAME)

CAMERA_HEALTH_DEGRADED_MESSAGE = "Camera health degraded on {camera_name}: {reason}"
CAMERA_HEALTH_RECOVERED_MESSAGE = "Camera health recovered on {camera_name}"

DEFAULT_RULES: dict[str, dict[str, str]] = {
    CAMERA_HEALTH_RULE_NAME: {
        "trigger": "camera_degraded",
        "message": CAMERA_HEALTH_DEGRADED_MESSAGE,
        "severity": "alert",
    },
    CAMERA_RECOVERY_RULE_NAME: {
        "trigger": "camera_recovered",
        "message": CAMERA_HEALTH_RECOVERED_MESSAGE,
        "severity": "info",
    },
}

# Wording an install may carry from before the rewording, mapped to the
# current template it should become.
_LEGACY_MESSAGES = {
    "{camera_name} camera health degraded: {reason}": CAMERA_HEALTH_DEGRADED_MESSAGE,
    "{camera_name} camera health recovered": CAMERA_HEALTH_RECOVERED_MESSAGE,
}


def default_rule_kwargs(name: str) -> dict:
    """Column kwargs for the lazily-installed system rule `name`.

    Both install sites build their Rule from this so the flag, template,
    trigger, and cooldown cannot drift between the API and the engine.
    """
    spec = DEFAULT_RULES[name]
    return {
        "name": name,
        "enabled": True,
        "is_system": True,
        "trigger_pattern": {"type": spec["trigger"]},
        "conditions": None,
        "actions": [{"type": "notify", "message": spec["message"]}],
        "cooldown_seconds": 3600,
        "severity": spec["severity"],
    }


def refreshed_default_rule_messages(name: str, actions: object) -> list | None:
    """Return a new actions list with legacy system-rule messages rewritten
    to the current template, or None when nothing needs to change.

    The caller must ASSIGN the returned list back to the ORM attribute.
    The first cut of this helper mutated the list in place and returned a
    bool — invisible to SQLAlchemy, whose plain JSON columns have no
    change tracking, so the backfill silently never persisted. Assignment
    is what marks the column dirty.

    Only the known system rules are touched; a user rule with the same
    wording by coincidence is left alone because the name has to match a
    system rule exactly.
    """
    if name not in DEFAULT_RULES or not isinstance(actions, list):
        return None
    changed = False
    new_actions = []
    for action in actions:
        if (
            isinstance(action, dict)
            and action.get("type") == "notify"
            and action.get("message") in _LEGACY_MESSAGES
        ):
            new_actions.append({**action, "message": _LEGACY_MESSAGES[action["message"]]})
            changed = True
        else:
            new_actions.append(action)
    return new_actions if changed else None
