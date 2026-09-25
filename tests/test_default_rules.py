"""Default camera-health rules: the shared templates and the legacy-message
backfill (issue #320). The ensure paths live behind a database, so the pure
contract is tested here: the two install sites must agree with
shared/default_rules, and existing installs carrying the pre-rewording
templates get them rewritten in place.
"""

from shared.default_rules import (
    CAMERA_HEALTH_DEGRADED_MESSAGE,
    CAMERA_HEALTH_RECOVERED_MESSAGE,
    CAMERA_HEALTH_RULE_NAME,
    CAMERA_RECOVERY_RULE_NAME,
    DEFAULT_RULES,
    DEFAULT_RULE_NAMES,
    refresh_default_rule_messages,
)


def test_default_rule_specs_are_consistent():
    assert set(DEFAULT_RULES) == {CAMERA_HEALTH_RULE_NAME, CAMERA_RECOVERY_RULE_NAME}
    for spec in DEFAULT_RULES.values():
        assert set(spec) == {"trigger", "message", "severity"}
    # The templates must lead with the event, not the camera: the old
    # "{camera_name} camera health …" phrasing duplicated the word camera
    # whenever the preview renderer fell back to "the camera".
    assert not CAMERA_HEALTH_DEGRADED_MESSAGE.startswith("{camera_name}")
    assert not CAMERA_HEALTH_RECOVERED_MESSAGE.startswith("{camera_name}")
    assert CAMERA_HEALTH_DEGRADED_MESSAGE.startswith("Camera health degraded")
    assert CAMERA_HEALTH_RECOVERED_MESSAGE.startswith("Camera health recovered")


def test_backfill_rewrites_legacy_messages_in_place():
    actions = [{"type": "notify", "message": "{camera_name} camera health degraded: {reason}"}]
    assert refresh_default_rule_messages(CAMERA_HEALTH_RULE_NAME, actions) is True
    assert actions[0]["message"] == CAMERA_HEALTH_DEGRADED_MESSAGE

    recovered = [{"type": "notify", "message": "{camera_name} camera health recovered"}]
    assert refresh_default_rule_messages(CAMERA_RECOVERY_RULE_NAME, recovered) is True
    assert recovered[0]["message"] == CAMERA_HEALTH_RECOVERED_MESSAGE


def test_backfill_is_idempotent():
    actions = [{"type": "notify", "message": CAMERA_HEALTH_DEGRADED_MESSAGE}]
    assert refresh_default_rule_messages(CAMERA_HEALTH_RULE_NAME, actions) is False
    assert actions[0]["message"] == CAMERA_HEALTH_DEGRADED_MESSAGE


def test_backfill_never_touches_user_rules_or_other_actions():
    user_rule = [{"type": "notify", "message": "{camera_name} camera health degraded: {reason}"}]
    assert refresh_default_rule_messages("My own rule", user_rule) is False
    assert user_rule[0]["message"] == "{camera_name} camera health degraded: {reason}"

    non_notify = [{"type": "email", "message": "{camera_name} camera health recovered"}]
    assert refresh_default_rule_messages(CAMERA_HEALTH_RULE_NAME, non_notify) is False

    assert refresh_default_rule_messages(CAMERA_HEALTH_RULE_NAME, None) is False
    assert refresh_default_rule_messages(CAMERA_HEALTH_RULE_NAME, "not-a-list") is False


def test_install_sites_use_the_shared_module():
    """Both lazy install paths must come from shared/default_rules so the
    templates cannot drift apart again."""
    import ast
    from pathlib import Path

    for path in (
        Path("services/api/routes/rules.py"),
        Path("services/events/engine.py"),
    ):
        source = path.read_text()
        assert "shared.default_rules" in source or "from shared.default_rules", (
            f"{path} does not import shared.default_rules"
        )
        assert '"{camera_name} camera health degraded' not in source, (
            f"{path} still hard-codes the legacy template"
        )


def test_default_rule_factory_marks_system_rules():
    """The lazily-installed rules must carry is_system so the UI can group
    them and the API can guard rename/delete (#317)."""
    from shared.default_rules import default_rule_kwargs

    for name in DEFAULT_RULE_NAMES:
        kwargs = default_rule_kwargs(name)
        assert kwargs["is_system"] is True
        assert kwargs["enabled"] is True
        assert kwargs["cooldown_seconds"] == 3600
        assert kwargs["severity"] == DEFAULT_RULES[name]["severity"]
        assert kwargs["actions"] == [{"type": "notify", "message": DEFAULT_RULES[name]["message"]}]
        assert kwargs["trigger_pattern"] == {"type": DEFAULT_RULES[name]["trigger"]}
