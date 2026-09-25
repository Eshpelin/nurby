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


def refresh_default_rule_messages(name: str, actions: object) -> bool:
    """Rewrite a legacy system-rule message to the current template, in
    place. Returns True when something changed (the caller persists).

    Only the known system rules are touched; a user rule with the same
    wording by coincidence is left alone because the name has to match a
    system rule exactly.
    """
    if name not in DEFAULT_RULES or not isinstance(actions, list):
        return False
    changed = False
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "notify":
            continue
        message = action.get("message")
        if message in _LEGACY_MESSAGES:
            action["message"] = _LEGACY_MESSAGES[message]
            changed = True
    return changed
