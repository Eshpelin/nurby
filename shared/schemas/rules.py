"""Rule create/update/response schemas, the action-chain and
trigger-pattern validators behind them, and rule test and
replay payloads. Scheduled reports ride here too.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator


# ── Rule schemas ──

_VALID_ACTION_TYPES = {
    "webhook", "api_call", "broadcast", "notify", "email", "vlm_call", "telegram",
    "verify", "locate", "device", "speak",
}


# The shape a `locate` action binds into vars, so {{vars.<output>.found}} etc.
# validate against the action chain's static ref check.
_LOCATE_OUTPUT_SCHEMA = {
    "properties": {
        "found": {"type": "boolean"},
        "count": {"type": "integer"},
        "label": {"type": "string"},
        "corroborated": {"type": "boolean"},
        "boxes": {"type": "array"},
    }
}


# Phase 2 inline-button actions. Kept in lockstep with
# ``services.events.actions.TELEGRAM_BUTTON_ACTIONS`` and the
# ``_CALLBACK_ACTIONS`` tuple in the Telegram poller. Phase 4 will add
# variants like ``name_cluster``; extending this set is the documented
# extension point.
_VALID_TELEGRAM_BUTTON_ACTIONS = {
    "ack",
    "mute_event",
    "snooze_rule",
    "open",
    # Phase 4. Deep-link to a cluster on the web (uses ``url=``) and
    # kick off an in-chat naming dialog. The cluster-naming actions are
    # only emitted by the system-initiated cluster prompts, not the
    # rule builder UI. Their schema validation still lives here so any
    # internal caller routes through the same allowlist.
    "open_cluster",
    "name_cluster_telegram",
    # Phase 4 stretch. yes/no follow-up answer captured onto event_notes.
    "yn_yes",
    "yn_no",
}


_MAX_TELEGRAM_BUTTONS = 4


def _validate_telegram_buttons(buttons, idx: int) -> None:
    if buttons is None:
        return
    if not isinstance(buttons, list):
        raise ValueError(f"action[{idx}] buttons must be a list")
    if len(buttons) > _MAX_TELEGRAM_BUTTONS:
        raise ValueError(
            f"action[{idx}] has {len(buttons)} buttons; max {_MAX_TELEGRAM_BUTTONS}"
        )
    for b_idx, btn in enumerate(buttons):
        if not isinstance(btn, dict):
            raise ValueError(f"action[{idx}].buttons[{b_idx}] must be an object")
        label = btn.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"action[{idx}].buttons[{b_idx}].label is required")
        b_action = btn.get("action")
        if b_action not in _VALID_TELEGRAM_BUTTON_ACTIONS:
            raise ValueError(
                f"action[{idx}].buttons[{b_idx}].action must be one of "
                f"{sorted(_VALID_TELEGRAM_BUTTON_ACTIONS)}"
            )
        if b_action == "open":
            url = btn.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(
                    f"action[{idx}].buttons[{b_idx}].url is required for action='open'"
                )
        if b_action in ("mute_event", "snooze_rule"):
            dur = btn.get("duration_seconds")
            if dur is not None:
                if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
                    raise ValueError(
                        f"action[{idx}].buttons[{b_idx}].duration_seconds must be a positive int"
                    )


def _validate_verify_action(action, idx: int) -> None:
    """Validate a ``verify`` action. question is a required non-empty
    string; min_confidence (if present) is a float in [0,1]; on_fail (if
    present) is one of {stop, continue}."""
    question = action.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"action[{idx}] verify requires a non-empty 'question'")

    mc = action.get("min_confidence")
    if mc is not None:
        if isinstance(mc, bool) or not isinstance(mc, (int, float)):
            raise ValueError(f"action[{idx}] verify min_confidence must be a number")
        if not (0.0 <= float(mc) <= 1.0):
            raise ValueError(f"action[{idx}] verify min_confidence must be in [0, 1]")

    on_fail = action.get("on_fail")
    if on_fail is not None and on_fail not in ("stop", "continue"):
        raise ValueError(f"action[{idx}] verify on_fail must be 'stop' or 'continue'")


def _validate_locate_action(action, idx: int) -> None:
    """Validate a ``locate`` (FindAnything) action. ``prompt`` is required;
    ``on_fail`` (if present) is stop|continue; ``min_overlap`` (if present) is a
    float in [0, 1]; ``require_corroboration`` (if present) is a bool. There is
    deliberately no ``min_confidence``. the model has no calibrated score."""
    prompt = action.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"action[{idx}] locate requires a non-empty 'prompt'")

    on_fail = action.get("on_fail")
    if on_fail is not None and on_fail not in ("stop", "continue"):
        raise ValueError(f"action[{idx}] locate on_fail must be 'stop' or 'continue'")

    mo = action.get("min_overlap")
    if mo is not None:
        if isinstance(mo, bool) or not isinstance(mo, (int, float)):
            raise ValueError(f"action[{idx}] locate min_overlap must be a number")
        if not (0.0 <= float(mo) <= 1.0):
            raise ValueError(f"action[{idx}] locate min_overlap must be in [0, 1]")

    rc = action.get("require_corroboration")
    if rc is not None and not isinstance(rc, bool):
        raise ValueError(f"action[{idx}] locate require_corroboration must be a boolean")


def _validate_device_action(action, idx):
    device_id = action.get("device_id")
    if not device_id:
        raise ValueError(f"action[{idx}] device action requires 'device_id'")
    try:
        uuid.UUID(str(device_id))
    except (ValueError, TypeError):
        raise ValueError(f"action[{idx}] device_id must be a UUID")
    extras = action.get("extras")
    if extras is not None and not isinstance(extras, dict):
        raise ValueError(f"action[{idx}] device extras must be an object")


def _validate_action_chain(actions):
    """Static checks. each action is a dict, has a known type, and
    any `{{vars.X.*}}` references point to an `output` declared by a
    previous vlm_call action in the chain.
    """
    import re

    from services.events.templates import collect_refs

    items = actions if isinstance(actions, list) else [actions] if isinstance(actions, dict) else []
    # `trigger` and `steps` are sequence-rule pseudo-outputs: on_complete /
    # on_timeout chains may reference {{vars.trigger.*}} (the start observation)
    # and {{vars.steps.N.*}} (each satisfied step). Always allowed; non-sequence
    # rules simply never populate them. See docs/sequence-rules-design.md.
    known_outputs: set[str] = {"trigger", "steps"}
    known_schemas: dict[str, dict] = {}

    for idx, action in enumerate(items):
        if not isinstance(action, dict):
            raise ValueError(f"action[{idx}] must be an object")
        a_type = action.get("type")
        if a_type not in _VALID_ACTION_TYPES:
            raise ValueError(f"action[{idx}] has unknown type '{a_type}'")

        if a_type == "telegram":
            _validate_telegram_buttons(action.get("buttons"), idx)

        if a_type == "verify":
            _validate_verify_action(action, idx)

        if a_type == "locate":
            _validate_locate_action(action, idx)

        if a_type == "device":
            _validate_device_action(action, idx)

        refs = collect_refs(action)
        for ref in refs:
            if not ref.startswith("vars."):
                continue
            tail = ref[len("vars."):]
            name = tail.split(".", 1)[0]
            if name not in known_outputs:
                raise ValueError(
                    f"action[{idx}] references vars.{name} but no prior action declares output '{name}'"
                )
            # Best-effort top-level schema key check.
            schema = known_schemas.get(name)
            if schema and "." in tail:
                nested = tail.split(".")[1]
                props = schema.get("properties") or {}
                if props and nested not in props:
                    raise ValueError(
                        f"action[{idx}] references vars.{name}.{nested} not in response_schema"
                    )

        if a_type == "vlm_call":
            output = action.get("output")
            if output:
                if not re.fullmatch(r"[a-zA-Z_][\w]*", output):
                    raise ValueError(f"action[{idx}] output '{output}' is not a valid identifier")
                known_outputs.add(output)
                if isinstance(action.get("response_schema"), dict):
                    known_schemas[output] = action["response_schema"]

        if a_type == "locate":
            output = action.get("output")
            if output:
                if not re.fullmatch(r"[a-zA-Z_][\w]*", output):
                    raise ValueError(f"action[{idx}] output '{output}' is not a valid identifier")
                known_outputs.add(output)
                known_schemas[output] = _LOCATE_OUTPUT_SCHEMA


def _validate_sequence(seq) -> None:
    """Validate a temporal `sequence` block on a trigger_pattern
    (docs/sequence-rules-design.md)."""
    if not isinstance(seq, dict):
        raise ValueError("trigger_pattern.sequence must be an object")
    steps = seq.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("sequence requires a non-empty 'steps' list")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"sequence step[{i}] must be an object")
        check = step.get("check")
        if not isinstance(check, dict) or not check.get("type"):
            raise ValueError(f"sequence step[{i}] needs a 'check' with a type")
        w = step.get("within_seconds")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or w <= 0:
            raise ValueError(f"sequence step[{i}] needs a positive 'within_seconds'")
        if check.get("type") == "locate":
            _validate_locate_action(check, i)
        if check.get("type") == "verify":
            _validate_verify_action(check, i)
        pre = step.get("pre_gate")
        if pre is not None and (not isinstance(pre, dict) or not pre.get("type")):
            raise ValueError(f"sequence step[{i}] pre_gate must be an object with a type")
        cf = step.get("confirm_frames")
        if cf is not None and (isinstance(cf, bool) or not isinstance(cf, int) or cf < 1):
            raise ValueError(f"sequence step[{i}] confirm_frames must be a positive integer")
    mode = seq.get("correlate_by")
    if mode is not None and mode not in ("person", "journey", "incident", "camera", "none"):
        raise ValueError("sequence correlate_by must be person|journey|incident|camera|none")
    refire = seq.get("on_refire")
    if refire is not None and refire not in ("ignore", "restart"):
        raise ValueError("sequence on_refire must be 'ignore' or 'restart'")
    ma = seq.get("max_active")
    if ma is not None and (isinstance(ma, bool) or not isinstance(ma, int) or ma <= 0):
        raise ValueError("sequence max_active must be a positive integer")
    cams = seq.get("cameras")
    if cams is not None and not isinstance(cams, list):
        raise ValueError("sequence cameras must be a list")
    on_timeout = seq.get("on_timeout")
    if on_timeout is not None:
        _validate_action_chain(on_timeout)


def _validate_trigger_pattern(trigger_pattern: dict) -> None:
    """Reject geometry-bound trigger shapes that cannot evaluate.

    Loitering and line_cross rules need both a polygon/segment AND a
    camera_id. speech_phrase rules need at least one phrase. The
    perception engine silently no-ops on bad shapes today, so we
    catch them at the API boundary and surface an inline-friendly
    error the frontend can render next to the field.
    """
    if not isinstance(trigger_pattern, dict):
        raise ValueError("trigger_pattern must be an object")

    t = trigger_pattern.get("type")

    seq = trigger_pattern.get("sequence")
    if seq is not None:
        _validate_sequence(seq)

    if t == "loitering":
        # Legacy zone_name mode is still supported (pipeline pre-
        # computes events). Only the inline-geometry mode needs
        # validation here.
        if "zone_name" in trigger_pattern and trigger_pattern.get("zone_name"):
            return
        pts = trigger_pattern.get("points")
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError(
                "Loitering rules need at least 3 zone points and a camera. "
                "Open the geometry editor."
            )
        if not trigger_pattern.get("camera_id"):
            raise ValueError(
                "Loitering rules need a camera_id so the zone is anchored to a feed."
            )

    elif t == "line_cross":
        if "zone_name" in trigger_pattern and trigger_pattern.get("zone_name"):
            return
        pts = trigger_pattern.get("points")
        if not isinstance(pts, list) or len(pts) != 2:
            raise ValueError(
                "Line-cross rules need exactly 2 points and a camera. "
                "Open the geometry editor."
            )
        if not trigger_pattern.get("camera_id"):
            raise ValueError(
                "Line-cross rules need a camera_id so the line is anchored to a feed."
            )

    elif t == "speech_phrase":
        phrases = trigger_pattern.get("phrases")
        if not isinstance(phrases, list) or not [p for p in phrases if str(p).strip()]:
            raise ValueError(
                "Speech-phrase rules need at least one non-empty phrase."
            )


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    trigger_pattern: dict
    conditions: dict | None = None
    actions: dict | list
    cooldown_seconds: int = 300
    severity: str = Field(default="alert", pattern="^(alert|detection)$")

    @field_validator("actions")
    @classmethod
    def _check_actions(cls, v):
        _validate_action_chain(v)
        return v

    @model_validator(mode="after")
    def _check_trigger(self):
        _validate_trigger_pattern(self.trigger_pattern)
        return self


class RuleUpdate(BaseModel):
    """Partial-update payload for PATCH /rules/{id}.

    Mirrors RuleCreate but every field is optional so the frontend can
    flip ``enabled`` or rename a rule without re-sending the trigger.
    Geometry validation only fires when ``trigger_pattern`` is set.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    trigger_pattern: dict | None = None
    conditions: dict | None = None
    actions: dict | list | None = None
    severity: str | None = Field(default=None, pattern="^(alert|detection)$")
    cooldown_seconds: int | None = None

    @field_validator("actions")
    @classmethod
    def _check_actions(cls, v):
        if v is None:
            return v
        _validate_action_chain(v)
        return v

    @model_validator(mode="after")
    def _check_trigger(self):
        if self.trigger_pattern is not None:
            _validate_trigger_pattern(self.trigger_pattern)
        return self


class RuleResponse(BaseModel):
    id: uuid.UUID
    name: str
    enabled: bool
    trigger_pattern: dict
    conditions: dict | None
    actions: dict | list
    cooldown_seconds: int
    severity: str = "alert"
    # Product-default rules (camera content health). The UI badges and
    # groups these; they cannot be renamed or deleted, only paused.
    is_system: bool = False
    snoozed_until: datetime | None = None
    created_at: datetime
    # Set on create when the rule takes a real-world action and was forced
    # disabled for review (#192). Absent/False on reads of stored rules.
    review_first: bool = False

    model_config = {"from_attributes": True}


# ── Scheduled reports ──

class ScheduledReportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1)
    person_id: uuid.UUID | None = None
    hour: int = Field(default=19, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    days: list[str] | None = None
    delivery: dict | None = None
    provider_id: uuid.UUID | None = None
    enabled: bool = True


class ScheduledReportUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    prompt: str | None = Field(default=None, min_length=1)
    person_id: uuid.UUID | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    days: list[str] | None = None
    delivery: dict | None = None
    provider_id: uuid.UUID | None = None
    enabled: bool | None = None


class ScheduledReportResponse(BaseModel):
    id: uuid.UUID
    name: str
    prompt: str
    person_id: uuid.UUID | None
    hour: int
    minute: int
    days: list | None
    delivery: dict | None
    provider_id: uuid.UUID | None
    enabled: bool
    last_run_at: datetime | None
    last_status: str | None
    last_output: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Rule test + replay schemas ──
#
# Both endpoints are pure dry-run. ``/rules/test`` never persists an
# event and never executes an action. ``/rules/{id}/replay`` only
# reads Observation rows and returns a tally plus sample matches.

class RuleTestRequest(BaseModel):
    """Payload for POST /api/rules/test.

    The trigger / conditions / actions fields mirror a normal rule body
    so the frontend can send the in-progress draft straight from the
    rule builder. ``camera_id`` and ``dry_run_observation`` are two
    escape hatches. when ``dry_run_observation`` is set, the synth
    step is skipped and the observation is used verbatim. when only
    ``camera_id`` is set, the most recent Observation row for that
    camera (within the last 1h) is used. Otherwise the engine
    synthesizes a permissive observation tailored to the trigger.
    """

    trigger_pattern: dict
    conditions: dict | None = None
    cooldown_seconds: int = 0
    actions: list[dict] = Field(default_factory=list)
    camera_id: uuid.UUID | None = None
    dry_run_observation: dict | None = None

    @field_validator("actions", mode="before")
    @classmethod
    def _coerce_actions(cls, v):
        # The rule builder sends a bare dict for a single action (the
        # same shape RuleCreate accepts). Normalize before list
        # validation so Test doesn't 422 on payloads Save accepts.
        if isinstance(v, dict):
            return [v]
        return v

    @field_validator("actions")
    @classmethod
    def _check_actions(cls, v):
        # Run the same chain validator that RuleCreate uses so the
        # frontend sees the same 422 errors before the rule is saved.
        if v:
            _validate_action_chain(v)
        return v

    @model_validator(mode="after")
    def _check_trigger(self):
        _validate_trigger_pattern(self.trigger_pattern)
        return self


class RuleTestActionPreview(BaseModel):
    """One entry in ``would_fire``. ``rendered_action`` is the action
    dict with every ``{{...}}`` token resolved against the synthesized
    observation, but the action itself is never executed."""

    index: int
    action_type: str
    rendered_action: dict


class RuleTestResponse(BaseModel):
    """Response for POST /api/rules/test.

    ``cooldown_active`` is always false for /test (there is no fired
    history to consult). It is kept in the response shape so the UI
    can render the same outcome panel for /test and the future
    "explain last fire" endpoint.
    """

    matched: bool
    reason: str
    matched_trigger: bool
    matched_conditions: bool
    schedule_blocked: bool
    cooldown_active: bool = False
    synthesized_observation: dict
    would_fire: list[RuleTestActionPreview] = Field(default_factory=list)
    # Non-fatal problems, e.g. a camera_id/person_id that matches no row.
    # The builder surfaces these before save.
    warnings: list[str] = Field(default_factory=list)


class RuleReplaySample(BaseModel):
    observation_id: uuid.UUID
    timestamp: datetime
    camera_id: uuid.UUID | None
    thumbnail_path: str | None
    snippet: str | None


class RuleReplayResponse(BaseModel):
    rule_id: uuid.UUID
    hours: int
    scanned: int
    matched: int
    first_matched_at: datetime | None
    last_matched_at: datetime | None
    samples: list[RuleReplaySample] = Field(default_factory=list)
