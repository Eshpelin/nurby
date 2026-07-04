"""Declarative registry of the rules vocabulary: trigger types, action
types, condition fields, and the temporal sequence block.

Single source of truth for GET /api/rules/schema. Consumed by the
frontend (instead of hardcoded enums) and by NL-rule-generation prompts.

Ground truth: field names and semantics are transcribed from the
executable code, not invented.
- triggers: services/events/engine.py _match_trigger
- actions: shared/schemas.py _validate_action_chain + services/events/actions.py
- conditions: services/events/engine.py _check_conditions (+ ignore_veto
  read in evaluate())
- sequence: shared/schemas.py _validate_sequence
Labels/descriptions/groups mirror frontend/src/components/rules/types.tsx.

Field entry shape:
  {"name", "type" (string|number|boolean|uuid|enum|points|list|object),
   "required", "enum"?, "default"?, "ref"? (camera|person|telegram_channel),
   "description"?}
"points" is a list of [x, y] pairs in frame coordinates.
"""

# Shared field fragments. Plain dicts; copied inline where semantics differ.
_CAMERA_FILTER = {
    "name": "camera_id", "type": "uuid", "required": False, "ref": "camera",
    "description": "Only match observations from this camera.",
}
_LABEL_FILTER = {
    "name": "label", "type": "string", "required": False,
    "description": "Only match tracked objects with this YOLO label.",
}

TRIGGER_TYPES: list[dict] = [
    {
        "type": "object_detected",
        "label": "Object detected",
        "description": "Person, car, dog, package, or any YOLO class.",
        "group": "vision",
        "fields": [
            {"name": "label", "type": "string", "required": False,
             "description": "YOLO class to match. Omit to fire on any detected object."},
            {"name": "zones", "type": "list", "required": False,
             "description": "Named zones the detection must intersect (any of)."},
            {"name": "object_state", "type": "enum", "required": False,
             "enum": ["moving", "stationary"],
             "description": "Parked-car filter. A detection with no track yet counts as moving."},
            {"name": "min_frames", "type": "number", "required": False, "default": 1,
             "description": "K-of-N persistence: require the match in this many frames before firing."},
            {"name": "within_seconds", "type": "number", "required": False, "default": 30,
             "description": "Window for min_frames persistence."},
            {"name": "min_area_pct", "type": "number", "required": False,
             "description": "Minimum bbox area as a fraction of the frame."},
            {"name": "max_area_pct", "type": "number", "required": False,
             "description": "Maximum bbox area as a fraction of the frame."},
            {"name": "min_ratio", "type": "number", "required": False,
             "description": "Minimum bbox width/height aspect ratio."},
            {"name": "max_ratio", "type": "number", "required": False,
             "description": "Maximum bbox width/height aspect ratio."},
        ],
    },
    {
        # UI shortcut, not an engine trigger type: the builder compiles it
        # into a `motion` trigger plus a prepended `locate` action (see
        # RuleBuilder.tsx). Listed for frontend parity.
        "type": "findanything",
        "label": "FindAnything",
        "description": (
            "Describe anything to look for. Adds a motion gate + a visual-condition "
            "action. GPU-heavy, so it only runs when the trigger fires and is "
            "throttled by the cooldown."
        ),
        "group": "vision",
        "fields": [
            {"name": "prompt", "type": "string", "required": True,
             "description": "What to look for. Becomes the prompt of the compiled locate action."},
        ],
    },
    {
        "type": "vehicle_detected",
        "label": "Vehicle / plate",
        "description": "A specific license plate, or any plate-identified vehicle.",
        "group": "vision",
        "fields": [
            {"name": "plate", "type": "string", "required": False,
             "description": "Plate text to match. Case-insensitive substring ('ABC' matches 'ABC123')."},
            {"name": "identified_only", "type": "boolean", "required": False, "default": False,
             "description": "Only fire on vehicles matched to a known vehicle identity."},
        ],
    },
    {
        "type": "face_detected",
        "label": "Face detected",
        "description": "Any face visible in frame, known or not.",
        "group": "faces",
        "fields": [],
    },
    {
        "type": "face_recognized",
        "label": "Known face",
        "description": "A specific person in your library.",
        "group": "faces",
        "fields": [
            {"name": "person_id", "type": "uuid", "required": False, "ref": "person",
             "description": "Person to match. Omit to fire on any recognized face."},
        ],
    },
    {
        "type": "face_unknown",
        "label": "Unknown face",
        "description": "Someone not yet matched to a person.",
        "group": "faces",
        "fields": [],
    },
    {
        "type": "motion",
        "label": "Motion",
        "description": "Pixel-level movement above a threshold.",
        "group": "motion",
        "fields": [
            {"name": "min_score", "type": "number", "required": False, "default": 0.01,
             "description": "Minimum motion score (0-1)."},
        ],
    },
    {
        "type": "audio_event",
        "label": "Audio event",
        "description": "Baby cry, scream, glass, alarm, bark, gunshot.",
        "group": "audio",
        "fields": [
            {"name": "label", "type": "enum", "required": False,
             "enum": ["baby_cry", "crying", "scream", "speech", "glass_break",
                      "alarm", "bark", "gunshot"],
             "description": "Audio class to match. Omit to fire on any audio event."},
            {"name": "min_score", "type": "number", "required": False, "default": 0.3,
             "description": "Minimum classifier score (0-1)."},
        ],
    },
    {
        "type": "clap_pattern",
        "label": "Clap pattern",
        "description": "Two, three, or more claps in a row.",
        "group": "audio",
        "fields": [
            {"name": "count", "type": "number", "required": False, "default": 2,
             "description": "Exact clap count (2 = double clap, 3 = triple)."},
            dict(_CAMERA_FILTER),
        ],
    },
    {
        "type": "speech_phrase",
        "label": "Spoken phrase",
        "description": "Fire when a phrase is said near a camera.",
        "group": "audio",
        "fields": [
            {"name": "phrases", "type": "list", "required": True,
             "description": "At least one non-empty phrase. Case-insensitive substring match on the transcript."},
            {"name": "match", "type": "enum", "required": False,
             "enum": ["any", "all"], "default": "any",
             "description": "'any' fires when one phrase appears; 'all' requires every phrase."},
            dict(_CAMERA_FILTER),
        ],
    },
    {
        "type": "loitering",
        "label": "Loitering",
        "description": "Someone stays inside a zone too long.",
        "group": "spatial",
        "fields": [
            {"name": "points", "type": "points", "required": True,
             "description": "Zone polygon, at least 3 points. Legacy alternative: zone_name."},
            {"name": "camera_id", "type": "uuid", "required": True, "ref": "camera",
             "description": "Camera the zone is anchored to. Required with points."},
            {"name": "threshold_seconds", "type": "number", "required": False, "default": 30,
             "description": "How long the subject must stay inside before firing."},
            dict(_LABEL_FILTER),
            {"name": "zone_name", "type": "string", "required": False,
             "description": "Legacy mode: named zone with pipeline-precomputed loitering events. Replaces points + camera_id."},
        ],
    },
    {
        "type": "line_cross",
        "label": "Tripwire",
        "description": "A tracked object crosses a line.",
        "group": "spatial",
        "fields": [
            {"name": "points", "type": "points", "required": True,
             "description": "Exactly 2 points defining the line. Legacy alternative: zone_name."},
            {"name": "camera_id", "type": "uuid", "required": True, "ref": "camera",
             "description": "Camera the line is anchored to. Required with points."},
            {"name": "direction", "type": "enum", "required": False,
             "enum": ["any", "in", "out"], "default": "any",
             "description": "Crossing direction relative to the line."},
            dict(_LABEL_FILTER),
            {"name": "zone_name", "type": "string", "required": False,
             "description": "Legacy mode: named tripwire with pipeline-precomputed events. Replaces points + camera_id."},
        ],
    },
    {
        "type": "camera_offline",
        "label": "Camera offline",
        "description": "A camera stops responding (tamper, power, network).",
        "group": "system",
        "fields": [
            {"name": "camera_id", "type": "uuid", "required": False, "ref": "camera",
             "description": "Only this camera. Omit to fire for any camera."},
        ],
    },
    {
        "type": "camera_online",
        "label": "Camera recovered",
        "description": "A camera comes back after being offline.",
        "group": "system",
        "fields": [
            {"name": "camera_id", "type": "uuid", "required": False, "ref": "camera",
             "description": "Only this camera. Omit to fire for any camera."},
        ],
    },
    {
        "type": "incident_started",
        "label": "Incident begins",
        "description": "A new cluster of repeat sightings opens (same person/vehicle keeps appearing).",
        "group": "system",
        "fields": [
            dict(_CAMERA_FILTER),
            {"name": "signature_kind", "type": "string", "required": False,
             "description": "Only incidents of this signature kind (e.g. person, vehicle)."},
        ],
    },
    {
        "type": "incident_ended",
        "label": "Incident recap",
        "description": "An incident closes: fires once with duration, count, and an AI recap.",
        "group": "system",
        "fields": [
            dict(_CAMERA_FILTER),
            {"name": "signature_kind", "type": "string", "required": False,
             "description": "Only incidents of this signature kind (e.g. person, vehicle)."},
            {"name": "min_duration_seconds", "type": "number", "required": False,
             "description": "Only incidents that lasted at least this long."},
            {"name": "min_occurrences", "type": "number", "required": False,
             "description": "Only incidents with at least this many sightings."},
        ],
    },
    {
        "type": "plate_list",
        "label": "Plate list",
        "description": (
            "Allow-list (alert on strangers) or block-list (alert on banned plates). "
            "Garage access control."
        ),
        "group": "traffic",
        "fields": [
            {"name": "mode", "type": "enum", "required": False,
             "enum": ["blacklist", "whitelist"], "default": "blacklist",
             "description": "blacklist fires on listed plates; whitelist fires on plates NOT listed."},
            {"name": "plates", "type": "list", "required": False,
             "description": "Plate strings. Normalized (case- and spacing-insensitive)."},
            {"name": "substring", "type": "boolean", "required": False, "default": False,
             "description": "Allow partial-plate matches."},
            {"name": "require_plate", "type": "boolean", "required": False, "default": True,
             "description": "Whitelist mode: when false, an unreadable plate also counts as unauthorized."},
        ],
    },
    {
        "type": "parking_violation",
        "label": "Parking spot",
        "description": "Reserve a spot for your plate. Alarm when anyone else parks there.",
        "group": "traffic",
        "fields": [
            {"name": "spot_zone", "type": "string", "required": True,
             "description": "Named zone covering the reserved spot."},
            {"name": "reserved_plates", "type": "list", "required": False,
             "description": "Authorized plates. Empty means alert on any vehicle that parks here."},
            {"name": "substring", "type": "boolean", "required": False, "default": False,
             "description": "Allow partial-plate matches."},
            {"name": "require_stationary", "type": "boolean", "required": False, "default": False,
             "description": "Require the vehicle to be matched to a stationary track (actually parked)."},
        ],
    },
    {
        "type": "wrong_way",
        "label": "Wrong way",
        "description": "A vehicle drives against the allowed direction over a lane line.",
        "group": "traffic",
        "fields": [
            {"name": "points", "type": "points", "required": True,
             "description": "Exactly 2 points defining the lane line."},
            dict(_CAMERA_FILTER),
            {"name": "allowed_direction", "type": "enum", "required": False,
             "enum": ["in", "out"], "default": "in",
             "description": "Allowed crossing direction; fires on the opposite."},
            dict(_LABEL_FILTER),
        ],
    },
    {
        "type": "speed_over",
        "label": "Speeding",
        "description": (
            "Time a vehicle between two gate lines a known distance apart. "
            "Approximate, not for citations."
        ),
        "group": "traffic",
        "fields": [
            {"name": "line_a", "type": "points", "required": True,
             "description": "First gate line, exactly 2 points."},
            {"name": "line_b", "type": "points", "required": True,
             "description": "Second gate line, exactly 2 points."},
            {"name": "distance_m", "type": "number", "required": True,
             "description": "Real-world distance between the gates, in meters."},
            {"name": "min_speed_kmh", "type": "number", "required": False, "default": 0,
             "description": "Fire only above this speed (km/h)."},
            dict(_LABEL_FILTER),
        ],
    },
    {
        "type": "red_light_cross",
        "label": "Crossed on red",
        "description": (
            "A vehicle crosses a line on red. Read the light from a signal zone, "
            "or set a red time window."
        ),
        "group": "traffic",
        "fields": [
            {"name": "points", "type": "points", "required": True,
             "description": "Exactly 2 points defining the stop line."},
            {"name": "signal_zone", "type": "string", "required": False,
             "description": "Named signal zone sampled for a red light. Wins over the time window when set."},
            {"name": "red_after", "type": "string", "required": False,
             "description": "Manual red window start, HH:MM."},
            {"name": "red_before", "type": "string", "required": False,
             "description": "Manual red window end, HH:MM."},
            {"name": "direction", "type": "enum", "required": False,
             "enum": ["any", "in", "out"], "default": "any",
             "description": "Crossing direction relative to the line."},
            dict(_LABEL_FILTER),
        ],
    },
    {
        "type": "crosswalk_violation",
        "label": "Crosswalk blocked",
        "description": "A vehicle sits in a crosswalk zone while a pedestrian is in it.",
        "group": "traffic",
        "fields": [
            {"name": "crosswalk_zone", "type": "string", "required": True,
             "description": "Named zone covering the crosswalk."},
            {"name": "vehicle_label", "type": "string", "required": False,
             "description": "Specific vehicle class. Default set: car, truck, bus, motorcycle, bicycle."},
        ],
    },
    {
        "type": "lane_occupancy",
        "label": "Lane congestion",
        "description": "Alert when several vehicles back up in a lane zone (optionally only when stopped).",
        "group": "traffic",
        "fields": [
            {"name": "lane_zone", "type": "string", "required": True,
             "description": "Named zone covering the lane."},
            {"name": "min_vehicles", "type": "number", "required": False, "default": 3,
             "description": "Fire once this many vehicles sit in the zone."},
            {"name": "label", "type": "string", "required": False,
             "description": "Specific vehicle class. Default set: car, truck, bus, motorcycle."},
            {"name": "require_stationary", "type": "boolean", "required": False, "default": False,
             "description": "Only count vehicles on stationary tracks (a true backup)."},
            {"name": "sustain_seconds", "type": "number", "required": False, "default": 0,
             "description": "Fire only after the lane held over the threshold this long. 0 fires immediately."},
        ],
    },
    {
        "type": "any",
        "label": "Any observation",
        "description": "Fire on every processed keyframe.",
        "group": "any",
        "fields": [],
    },
]

# Fields shared by webhook and api_call.
_HTTP_ACTION_FIELDS = [
    {"name": "url", "type": "string", "required": True,
     "description": "Target URL. Template variables allowed."},
    {"name": "auth", "type": "object", "required": False,
     "description": ("Auth block: {type: bearer|api_key|basic, token?, header?, "
                     "key?, username?, password?}.")},
    {"name": "secret", "type": "string", "required": False,
     "description": "HMAC-SHA256 signing secret. Signature sent in X-Nurby-Signature."},
    {"name": "payload_template", "type": "object", "required": False,
     "description": "Custom JSON body with {{...}} template variables. Omit for the default payload."},
]

ACTION_TYPES: list[dict] = [
    {
        "type": "webhook",
        "label": "Webhook",
        "description": "POST the event payload to a URL.",
        "group": "delivery",
        "fields": [dict(f) for f in _HTTP_ACTION_FIELDS],
    },
    {
        "type": "api_call",
        "label": "API Call",
        "description": "Call an HTTP API with a chosen method and payload.",
        "group": "delivery",
        "fields": [
            {"name": "method", "type": "enum", "required": False,
             "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "POST",
             "description": "HTTP method."},
            *[dict(f) for f in _HTTP_ACTION_FIELDS],
        ],
    },
    {
        "type": "broadcast",
        "label": "WebSocket broadcast",
        "description": "Push the event to connected web clients over WebSocket.",
        "group": "delivery",
        "fields": [
            {"name": "payload_template", "type": "object", "required": False,
             "description": "Custom JSON body with {{...}} template variables. Omit for the default payload."},
        ],
    },
    {
        "type": "notify",
        "label": "Notification",
        "description": "Create an in-app notification.",
        "group": "notify",
        "fields": [
            {"name": "message", "type": "string", "required": False,
             "default": "Rule '{rule_name}' triggered",
             "description": "Notification text. Template variables allowed."},
            {"name": "severity", "type": "enum", "required": False,
             "enum": ["info", "warning", "critical"], "default": "info"},
        ],
    },
    {
        "type": "email",
        "label": "Email",
        "description": "Send an email alert.",
        "group": "notify",
        "fields": [
            {"name": "to", "type": "string", "required": True,
             "description": "Recipient address."},
            {"name": "subject", "type": "string", "required": False,
             "description": "Subject line. Template variables allowed."},
            {"name": "body", "type": "string", "required": False,
             "description": "Body text. Template variables allowed."},
        ],
    },
    {
        "type": "telegram",
        "label": "Telegram",
        "description": "Send a Telegram message via a paired channel, optionally with inline buttons.",
        "group": "notify",
        "fields": [
            {"name": "channel_id", "type": "uuid", "required": True, "ref": "telegram_channel",
             "description": "Paired Telegram channel to send through."},
            {"name": "template", "type": "string", "required": False,
             "description": "Message template with {var} placeholders."},
            {"name": "silent", "type": "boolean", "required": False, "default": False,
             "description": "Deliver without a notification sound."},
            {"name": "include_thumbnail", "type": "boolean", "required": False, "default": False,
             "description": "Attach the observation thumbnail."},
            {"name": "buttons", "type": "list", "required": False,
             "description": ("Up to 4 inline buttons: {label, action: ack|mute_event|snooze_rule|open, "
                             "url? (open), duration_seconds? (mute_event/snooze_rule)}.")},
        ],
    },
    {
        "type": "vlm_call",
        "label": "VLM Call",
        "description": "Ask a vision-language model about the frame and bind the answer to a variable.",
        "group": "ai",
        "fields": [
            {"name": "provider", "type": "enum", "required": False,
             "enum": ["openai", "anthropic", "gemini", "ollama"], "default": "openai"},
            {"name": "model", "type": "string", "required": False,
             "description": "Model name for the provider."},
            {"name": "system", "type": "string", "required": False,
             "default": "{{defaults.system}}",
             "description": "System prompt."},
            {"name": "prompt", "type": "string", "required": False,
             "default": "Describe the scene.",
             "description": "User prompt. Template variables allowed."},
            {"name": "attach_image", "type": "boolean", "required": False, "default": False,
             "description": "Attach the observation frame to the request."},
            {"name": "response_schema", "type": "object", "required": False,
             "description": "JSON Schema for structured output. Enables {{vars.<output>.<key>}} refs."},
            {"name": "output", "type": "string", "required": False,
             "description": "Identifier later actions use as {{vars.<output>...}}."},
            {"name": "max_retries", "type": "number", "required": False, "default": 1},
            {"name": "on_error", "type": "enum", "required": False,
             "enum": ["continue", "stop", "fallback"], "default": "continue",
             "description": "'stop' aborts the chain; 'fallback' binds fallback_value to the output."},
            {"name": "fallback_value", "type": "string", "required": False,
             "description": "Value bound to the output when on_error is 'fallback'."},
            {"name": "timeout_ms", "type": "number", "required": False, "default": 20000},
        ],
    },
    {
        "type": "verify",
        "label": "Verify with AI",
        "description": "Ask a VLM a yes/no question about the frame; gate the rest of the chain on the answer.",
        "group": "ai",
        "fields": [
            {"name": "question", "type": "string", "required": True,
             "description": "Yes/no question about the frame."},
            {"name": "min_confidence", "type": "number", "required": False, "default": 0.6,
             "description": "Minimum confidence, in [0, 1], for a yes to count as a pass."},
            {"name": "on_fail", "type": "enum", "required": False,
             "enum": ["stop", "continue"], "default": "stop",
             "description": "'stop' aborts later actions when the answer is no/uncertain."},
            {"name": "provider_id", "type": "uuid", "required": False,
             "description": "Specific VLM provider. Omit for the household default."},
        ],
    },
    {
        "type": "locate",
        "label": "Visual condition (FindAnything)",
        "description": ("Run the visual grounding model on the triggering frame; gate the rest "
                        "of the chain on whether the description is found."),
        "group": "ai",
        "fields": [
            {"name": "prompt", "type": "string", "required": True,
             "description": "Free-text description of what to locate."},
            {"name": "on_fail", "type": "enum", "required": False,
             "enum": ["stop", "continue"], "default": "stop",
             "description": "'stop' aborts later actions when nothing is found."},
            {"name": "require_corroboration", "type": "boolean", "required": False, "default": False,
             "description": "Only count a located box that overlaps a real detection. No confidence slider; the model has no calibrated score."},
            {"name": "min_overlap", "type": "number", "required": False, "default": 0.1,
             "description": "IoU threshold, in [0, 1], for corroboration."},
            {"name": "output", "type": "string", "required": False, "default": "loc",
             "description": "Identifier for {{vars.<output>.found|count|label|corroborated|boxes}}."},
        ],
    },
    {
        "type": "device",
        "label": "Device",
        "group": "delivery",
        "description": (
            "Trigger a registered physical device (buzzer, relay, speaker). "
            "The device's endpoint, secret and payload resolve at fire time."
        ),
        "fields": [
            {"name": "device_id", "type": "uuid", "required": True, "ref": "device",
             "description": "Registered device to fire (Settings → Devices)."},
            {"name": "extras", "type": "object", "required": False,
             "description": "Extra keys merged into the device payload. Template variables allowed."},
        ],
    },
]

# Rule-level `conditions` object, evaluated after the trigger matches.
CONDITION_FIELDS: list[dict] = [
    {"name": "camera_id", "type": "uuid", "required": False, "ref": "camera",
     "description": "Single-camera filter. Ignored when camera_ids is set."},
    {"name": "camera_ids", "type": "list", "required": False, "ref": "camera",
     "description": "Camera allow-list. The observation's camera must be in it."},
    {"name": "days", "type": "list", "required": False,
     "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
     "description": "Days of week the rule is active (household timezone)."},
    {"name": "time_after", "type": "string", "required": False,
     "description": "Active window start, HH:MM inclusive. time_after > time_before wraps midnight."},
    {"name": "time_before", "type": "string", "required": False,
     "description": "Active window end, HH:MM inclusive."},
    {"name": "min_confidence", "type": "number", "required": False,
     "description": "Minimum detection/VLM confidence, in [0, 1]. Skipped when no confidence signal exists."},
    {"name": "ignore_veto", "type": "boolean", "required": False, "default": False,
     "description": "Fire even while an alert veto (e.g. household disarm) is active."},
]

# trigger_pattern.sequence: temporal multi-step rules. The base trigger is
# step 0; steps are the ordered "and then" checks. Mirrors
# shared/schemas.py _validate_sequence and docs/sequence-rules-design.md.
SEQUENCE_SCHEMA: dict = {
    "description": (
        "Optional temporal block on trigger_pattern. The base trigger starts the "
        "sequence; each step must then be satisfied, in order, within its window. "
        "on_complete reuses the rule's main action chain; on_timeout fires when a "
        "step never happens in time (absence alert)."
    ),
    "fields": [
        {"name": "steps", "type": "list", "required": True,
         "description": "Ordered step objects. At least one."},
        {"name": "correlate_by", "type": "enum", "required": False,
         "enum": ["person", "journey", "incident", "camera", "none"],
         "description": "How later observations are bound to the sequence subject."},
        {"name": "on_refire", "type": "enum", "required": False,
         "enum": ["ignore", "restart"],
         "description": "What a re-fire of the base trigger does to an active sequence."},
        {"name": "max_active", "type": "number", "required": False,
         "description": "Cap on concurrently tracked sequences for this rule."},
        {"name": "cameras", "type": "list", "required": False, "ref": "camera",
         "description": "Cameras whose observations may satisfy steps."},
        {"name": "on_timeout", "type": "list", "required": False,
         "description": "Action chain (same shape as rule actions) fired when a step times out."},
    ],
    "step_fields": [
        {"name": "check", "type": "object", "required": True,
         "description": ("What satisfies the step: {type: object_detected, label} or a locate/verify "
                         "action shape ({type: locate, prompt, require_corroboration?} / "
                         "{type: verify, question, min_confidence?})."),
         "enum": ["object_detected", "locate", "verify"]},
        {"name": "within_seconds", "type": "number", "required": True,
         "description": "Window, from the previous step, in which the check must pass. Positive."},
        {"name": "confirm_frames", "type": "number", "required": False, "default": 1,
         "description": "Require this many agreeing frames within the window (>1 cuts noise)."},
        {"name": "negate", "type": "boolean", "required": False, "default": False,
         "description": "Match on ABSENCE. With ordering this expresses a transition."},
        {"name": "pre_gate", "type": "object", "required": False,
         "description": ("Cheap gate that must match before an expensive check runs, e.g. "
                         "{type: object_detected, label}. Locate steps only.")},
    ],
}


def build_schema() -> dict:
    """Response body for GET /api/rules/schema."""
    return {
        "triggers": TRIGGER_TYPES,
        "actions": ACTION_TYPES,
        "conditions": CONDITION_FIELDS,
        "sequence": SEQUENCE_SCHEMA,
    }
